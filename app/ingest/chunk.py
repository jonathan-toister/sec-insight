"""Chunking: split a filing's clean text into embeddable pieces."""
import re
from dataclasses import dataclass

# ~600 tokens * ~4 chars/token = 2400 chars per chunk, 12% overlap
_TARGET_CHARS = 2400
_OVERLAP_CHARS = 288

# Matches SEC filing section headings: "Item 1.", "ITEM 1A. Risk Factors", etc.
_SECTION_RE = re.compile(
    r"^(item\s+\d+[a-z]?\.?\s+\S.{0,80})", re.IGNORECASE | re.MULTILINE
)


@dataclass
class RawChunk:
    text: str
    section: str | None
    chunk_index: int


def _split_para(para: str) -> list[str]:
    """Break an oversized paragraph at single-newline boundaries.
    Handles the case where an entire section has no double-newlines
    (e.g. financial tables, dense XBRL output).
    """
    if len(para) <= _TARGET_CHARS:
        return [para]
    sub: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in para.split("\n"):
        line_len = len(line) + 1
        if current and current_len + line_len > _TARGET_CHARS:
            sub.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += line_len
    if current:
        sub.append("\n".join(current))
    return sub


def split_text(text: str) -> list[RawChunk]:
    """
    Split filing text into overlapping chunks of ~600 tokens each.
    Splits on paragraph boundaries; detects "Item N" headings and attaches
    the current section name to each chunk for citation purposes.
    """
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[RawChunk] = []
    current_section: str | None = None
    buffer: list[str] = []
    buffer_len = 0
    chunk_index = 0

    for raw_para in paragraphs:
        for para in _split_para(raw_para):
            if _SECTION_RE.match(para):
                current_section = para.split("\n")[0].strip()[:100]

            para_len = len(para)

            if buffer and buffer_len + para_len > _TARGET_CHARS:
                chunk_text = "\n\n".join(buffer)
                chunks.append(
                    RawChunk(
                        text=chunk_text,
                        section=current_section,
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1

                tail = chunk_text[-_OVERLAP_CHARS:]
                buffer = [tail] if tail.strip() else []
                buffer_len = len(tail)

            buffer.append(para)
            buffer_len += para_len + 2

    if buffer:
        chunk_text = "\n\n".join(buffer)
        if chunk_text.strip():
            chunks.append(
                RawChunk(
                    text=chunk_text,
                    section=current_section,
                    chunk_index=chunk_index,
                )
            )

    return chunks
