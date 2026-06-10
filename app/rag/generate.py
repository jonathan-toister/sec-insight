"""Answer generation with Claude."""
import anthropic

from app.config import settings
from app.schemas import ChunkResult

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

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
            "answer": {
                "type": "string",
                "description": "Plain-English answer with inline citations",
            },
            "chunk_highlights": {
                "type": "array",
                "description": (
                    "Per-chunk highlights in the same order as the provided excerpts."
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
        "required": ["answer", "chunk_highlights"],
    },
}


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
