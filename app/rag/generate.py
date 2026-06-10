"""Answer generation with Claude."""
import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.schemas import ChunkResult

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
  1. Call search_filings to find relevant information (ticker is required — \
extract it from the question).
  2. If the results are empty, try rephrasing the query or inform the user \
that the company may not be ingested.
  3. Once you have enough context, call format_answer with \
response_type="research".
  4. Every factual claim must cite its source as [Company Form_Type FY####].
  5. Write in plain, simple English. Briefly explain financial jargon in \
parentheses the first time you use it.
  6. End your answer with "Disclaimer: This is not investment advice."

For conversational messages (greetings, thanks, off-topic):
  Call format_answer directly with response_type="conversational", \
chunk_highlights=[], and a friendly reply — no citations, no disclaimer.

Never answer from your own knowledge about specific filing contents. \
Always use search_filings first. If you cannot identify the company ticker \
from the question, ask the user to clarify before searching.\
"""


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


async def run_agent(
    question: str,
    session: AsyncSession,
) -> tuple[str, list[str], dict[int, list[str]], list[ChunkResult]]:
    """
    Agentic loop: Claude decides when to call search_filings; loops until it
    calls format_answer or hits max turns.

    Returns (answer, sources, highlights_map, all_chunks).
    """
    from app.tools.registry import TOOL_SCHEMAS, dispatch  # avoid circular import at module level

    messages: list[dict] = [{"role": "user", "content": question}]
    all_chunks: list[ChunkResult] = []

    for _ in range(_MAX_TURNS):
        response = await _client.messages.create(
            model=settings.chat_model,
            max_tokens=2048,
            system=_AGENT_SYSTEM_PROMPT,
            tools=[*TOOL_SCHEMAS, _FORMAT_TOOL],  # type: ignore[list-item]
            tool_choice={"type": "auto"},
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            text = next(
                (b.text for b in response.content if hasattr(b, "text")), ""
            )
            return text, [], {}, []

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        tool_results = []

        for tu in tool_uses:
            if tu.name == "format_answer":
                tool_input: dict = tu.input  # type: ignore[union-attr]
                answer = tool_input["answer"].strip()
                if tool_input.get("response_type") == "conversational":
                    return answer, [], {}, []

                highlights_map: dict[int, list[str]] = {
                    item["chunk_index"]: item.get("highlights", [])
                    for item in tool_input.get("chunk_highlights", [])
                    if isinstance(item.get("chunk_index"), int)
                }
                return answer, _build_sources(all_chunks), highlights_map, all_chunks

            try:
                content = await dispatch(
                    tu.name,
                    tu.input,  # type: ignore[union-attr]
                    session,
                    all_chunks,
                    len(all_chunks),
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
