"""Answer generation with Claude."""
import logging
import time

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.schemas import ChunkResult

_logger = logging.getLogger(__name__)

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

_MAX_TURNS = 10

_SYSTEM_PROMPT = """\
You are a helpful assistant that explains SEC filings to everyday investors who \
don't have a finance background. Answer the investor's question using ONLY the \
provided SEC filing excerpts. Do not use any outside knowledge.

Rules:
1. Write in plain, simple English. Avoid financial jargon. When you must use a \
   financial term (e.g. "revenue", "amortization"), briefly explain it in \
   parentheses the first time you use it.
2. Every factual claim must cite its source using the format \
   [Company Form_Type FY####].
3. If the excerpts do not contain enough information to answer, say so explicitly.
4. Do not speculate or extrapolate beyond the text.
5. End your response with "Disclaimer: This is not investment advice."

For each excerpt, also identify the 1–3 sentences or phrases most directly \
relevant to the question and copy them verbatim into chunk_highlights.\
"""

_FORMAT_TOOL: anthropic.types.ToolParam = {
    "name": "format_answer",
    "description": "Return a plain-English answer and per-chunk relevant highlights.",
    "input_schema": {
        "type": "object",
        "properties": {
            "response_type": {
                "type": "string",
                "enum": ["research", "conversational"],
                "description": (
                    "Use 'conversational' for greetings, thanks, or off-topic messages. "
                    "Use 'research' for SEC filing questions that required searching."
                ),
            },
            "answer": {
                "type": "string",
                "description": "Plain-English answer with inline citations",
            },
            "chunk_highlights": {
                "type": "array",
                "description": (
                    "Per-chunk highlights in the same order as the provided excerpts. "
                    "Empty list for conversational responses."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "chunk_index": {
                            "type": "integer",
                            "description": "1-based index matching [N] in the context",
                        },
                        "highlights": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Verbatim phrases/sentences from this chunk most "
                                "relevant to the question (1–3 items)"
                            ),
                        },
                    },
                    "required": ["chunk_index", "highlights"],
                },
            },
        },
        "required": ["response_type", "answer", "chunk_highlights"],
    },
}

_AGENT_SYSTEM_PROMPT = """\
You are an SEC filings assistant that helps investors understand company filings.

For SEC filing questions:
  1. Call list_filings(ticker) to check what is already indexed before searching.
     If the filing exists (status=ingested), proceed to search_filings.
     If the filing is missing, offer to ingest it (call ingest_filing).
     If the filing is already ingesting (status=ingesting), tell the user and \
offer to wait.
  2. Call search_filings to find relevant information (ticker is required — \
extract it from the question).
  3. If search results are empty, try rephrasing the query.
  4. Once you have enough context, call format_answer with \
response_type="research".
  5. Every factual claim must cite its source as [Company Form_Type FY####].
  6. Write in plain, simple English. Briefly explain financial jargon in \
parentheses the first time you use it.
  7. End your answer with "Disclaimer: This is not investment advice."

Ingest workflow:
  - Single filing + dependent question ("ingest X and tell me Y"):
      Call ingest_filing, then immediately call \
check_ingest_status(job_id, wait=true).
      This blocks until ingestion completes (up to 10 min) so you can search \
and answer in the same turn.
  - Bulk ingest ("ingest these 5 filings"):
      Enqueue all with ingest_filing, acknowledge each, do NOT block.
      Tell the user to ask their question once ingestion is complete.
  - status="ingesting": do NOT say "I don't have that" or return empty results.
      Report that the filing is still being ingested and offer to wait \
(check_ingest_status(wait=true)) or be re-asked later.
  - status="failed": report the error and ask whether to retry \
(call ingest_filing again).
  - "what companies do you have?" → call list_companies().
  - "what filings do you have for X?" → call list_filings(ticker=X).

For conversational messages (greetings, thanks, off-topic):
  Call format_answer directly with response_type="conversational", \
chunk_highlights=[], and a friendly reply — no citations, no disclaimer.

Never answer from your own knowledge about specific filing contents. \
Always use search_filings first. If you cannot identify the company ticker \
from the question, ask the user to clarify before searching.\
"""

# Cached system prompt — stable across all turns, only charged once per cache TTL.
_CACHED_SYSTEM: list[dict] = [
    {"type": "text", "text": _AGENT_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
]


def _log_usage(response: anthropic.types.Message, label: str = "turn") -> None:
    u = response.usage
    _logger.info(
        "token_usage label=%s model=%s input=%d output=%d cache_read=%d cache_write=%d",
        label,
        response.model,
        u.input_tokens,
        u.output_tokens,
        getattr(u, "cache_read_input_tokens", 0),
        getattr(u, "cache_creation_input_tokens", 0),
    )


def _tag_last_for_cache(messages: list[dict]) -> list[dict]:
    """Return messages with cache_control on the last content block of the last message."""
    if not messages:
        return messages
    out = list(messages)
    last = out[-1]
    content = last["content"]
    if isinstance(content, str):
        out[-1] = {
            **last,
            "content": [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}],
        }
    elif isinstance(content, list) and content:
        blocks = list(content)
        tail = blocks[-1]
        if isinstance(tail, dict):
            blocks[-1] = {**tail, "cache_control": {"type": "ephemeral"}}
        out[-1] = {**last, "content": blocks}
    return out


def _format_chunks(chunks: list[ChunkResult]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        header = f"[{i}] {chunk.company} {chunk.form_type}"
        if chunk.fiscal_year:
            header += f" FY{chunk.fiscal_year}"
        if chunk.section:
            header += f" — {chunk.section}"
        parts.append(f"{header}\n{chunk.text}")
    return "\n\n".join(parts)


def _build_sources(chunks: list[ChunkResult]) -> list[str]:
    seen: set[str] = set()
    sources: list[str] = []
    for chunk in chunks:
        cite = f"{chunk.company} {chunk.form_type}"
        if chunk.fiscal_year:
            cite += f" FY{chunk.fiscal_year}"
        if chunk.section:
            cite += f" — {chunk.section}"
        if cite not in seen:
            seen.add(cite)
            sources.append(cite)
    return sources


def _accumulate_usage(totals: dict, response: anthropic.types.Message) -> None:
    u = response.usage
    totals["input_tokens"] += u.input_tokens
    totals["output_tokens"] += u.output_tokens
    totals["cache_read_tokens"] += getattr(u, "cache_read_input_tokens", 0)
    totals["cache_write_tokens"] += getattr(u, "cache_creation_input_tokens", 0)
    totals["model"] = response.model


async def run_agent(
    question: str,
    session: AsyncSession,
    prior_messages: list[dict] | None = None,
    conversation_id: int | None = None,
    arq_redis=None,
) -> tuple[str, list[str], dict[int, list[str]], list[ChunkResult], dict]:
    """
    Agentic loop: Claude decides when to call tools; loops until it calls
    format_answer or hits max turns.

    Returns (answer, sources, highlights_map, all_chunks, usage).
    usage keys: input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                model, latency_ms.
    """
    from app.tools.registry import TOOL_SCHEMAS, dispatch  # avoid circular import at module level

    tools_with_cache = [
        *TOOL_SCHEMAS,
        {**_FORMAT_TOOL, "cache_control": {"type": "ephemeral"}},
    ]

    messages: list[dict] = list(prior_messages or [])
    messages.append({"role": "user", "content": question})
    all_chunks: list[ChunkResult] = []
    usage: dict = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "model": settings.chat_model,
    }
    t_start = time.perf_counter()

    for turn in range(_MAX_TURNS):
        response = await _client.messages.create(
            model=settings.chat_model,
            max_tokens=2048,
            system=_CACHED_SYSTEM,  # type: ignore[arg-type]
            tools=tools_with_cache,  # type: ignore[list-item]
            tool_choice={"type": "auto"},
            messages=_tag_last_for_cache(messages),  # type: ignore[arg-type]
        )
        _log_usage(response, label=f"turn={turn}")
        _accumulate_usage(usage, response)

        if response.stop_reason == "end_turn":
            text = next(
                (b.text for b in response.content if hasattr(b, "text")), ""
            )
            usage["latency_ms"] = int((time.perf_counter() - t_start) * 1000)
            return text, [], {}, [], usage

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        tool_results = []

        for tu in tool_uses:
            if tu.name == "format_answer":
                tool_input: dict = tu.input  # type: ignore[union-attr]
                answer = tool_input["answer"].strip()
                usage["latency_ms"] = int((time.perf_counter() - t_start) * 1000)
                if tool_input.get("response_type") == "conversational":
                    return answer, [], {}, [], usage

                highlights_map: dict[int, list[str]] = {
                    item["chunk_index"]: item.get("highlights", [])
                    for item in tool_input.get("chunk_highlights", [])
                    if isinstance(item.get("chunk_index"), int)
                }
                return answer, _build_sources(all_chunks), highlights_map, all_chunks, usage

            try:
                content = await dispatch(
                    tu.name,
                    tu.input,  # type: ignore[union-attr]
                    session,
                    all_chunks,
                    len(all_chunks),
                    conversation_id=conversation_id,
                    arq_redis=arq_redis,
                )
            except ValueError as exc:
                content = f"Tool error: {exc}"

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": content,
                }
            )

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError("Agent loop exceeded max turns without a final answer.")


async def generate_answer(
    question: str,
    chunks: list[ChunkResult],
) -> tuple[str, list[str], dict[int, list[str]]]:
    """
    Generate a plain-English grounded answer from retrieved chunks using Claude.

    Returns (answer, sources, highlights_map) where highlights_map maps
    1-based chunk index to a list of verbatim highlight strings.
    """
    context = _format_chunks(chunks)
    user_content = f"Filing excerpts:\n\n{context}\n\nQuestion: {question}"

    message = await _client.messages.create(
        model=settings.chat_model,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        tools=[_FORMAT_TOOL],
        tool_choice={"type": "tool", "name": "format_answer"},
        messages=[{"role": "user", "content": user_content}],
    )

    tool_block = next(
        (b for b in message.content if b.type == "tool_use"),
        None,
    )
    if tool_block is None:
        raise RuntimeError(f"Claude did not return a tool_use block. Content: {message.content}")

    tool_input: dict = tool_block.input  # type: ignore[union-attr]
    answer: str = tool_input["answer"].strip()
    raw_highlights: list[dict] = tool_input.get("chunk_highlights", [])

    highlights_map: dict[int, list[str]] = {
        item["chunk_index"]: item.get("highlights", [])
        for item in raw_highlights
        if isinstance(item.get("chunk_index"), int)
    }

    sources = _build_sources(chunks)
    return answer, sources, highlights_map
