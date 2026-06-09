"""Answer generation with Claude."""
import anthropic

from app.config import settings
from app.schemas import ChunkResult

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

_SYSTEM_PROMPT = """\
You are a financial analyst assistant. Answer the investor's question using ONLY \
the provided SEC filing excerpts. Do not use any outside knowledge.

Rules:
1. Every factual claim must cite its source using the format [Company Form_Type FY####].
2. If the excerpts do not contain enough information to answer, say so explicitly.
3. Use precise financial language. Do not speculate or extrapolate beyond the text.
4. End your response with "Disclaimer: This is not investment advice."\
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


async def generate_answer(
    question: str,
    chunks: list[ChunkResult],
) -> tuple[str, list[str]]:
    """
    Generate a grounded answer from retrieved chunks using Claude.
    Passes the original question (not the HyDE document) so the answer
    addresses what the user actually asked.
    """
    context = _format_chunks(chunks)
    user_content = f"Filing excerpts:\n\n{context}\n\nQuestion: {question}"

    message = await _client.messages.create(
        model=settings.chat_model,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    answer = message.content[0].text.strip()
    sources = _build_sources(chunks)
    return answer, sources
