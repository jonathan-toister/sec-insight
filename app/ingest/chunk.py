"""Chunking: split a filing's clean text into embeddable pieces."""
import re
from dataclasses import dataclass

# ~600 tokens * ~4 chars/token = 2400 chars per chunk
_TARGET_CHARS = 2400
_OVERLAP_CHARS = 288
# How far back to search for a sentence boundary when trimming a chunk
_SENT_SEARCH = 300

# Fallback: matches SEC filing item headings in plain text
_SECTION_RE = re.compile(
    r"^(item\s+\d+[a-z]?\.?\s+\S.{0,80})", re.IGNORECASE | re.MULTILINE
)
# Extracts item_number and heading from "Item 1A. Risk Factors" style strings
_ITEM_PARSE_RE = re.compile(
    r"item\s+(\d+[a-z]?)\.?\s*(.*)", re.IGNORECASE
)
# Sentence boundary: period/!/? followed by whitespace + uppercase letter
_SENT_BOUNDARY_RE = re.compile(r"[.!?]\s+[A-Z]")
# Table heuristic: ≥3 lines each with ≥3 pipe-separated or tab-separated tokens
_TABLE_ROW_RE = re.compile(r"(\|[^\|]+){3,}|(\t[^\t]+){3,}")


@dataclass
class RawChunk:
    text: str
    section: str | None      # compat label e.g. "Item 1A. Risk Factors"
    item_number: str | None  # "1A"
    heading: str | None      # "Risk Factors"
    is_table: bool
    chunk_index: int


@dataclass
class _Section:
    item_number: str | None
    heading: str | None
    text: str
    start_offset: int  # char offset in original text where this section starts


def _parse_item(heading_text: str) -> tuple[str | None, str | None]:
    """Extract (item_number, heading_title) from 'Item 1A. Risk Factors'."""
    m = _ITEM_PARSE_RE.match(heading_text.strip())
    if m:
        return m.group(1).upper(), m.group(2).strip()
    return None, heading_text.strip() or None


def _split_para(para: str) -> list[str]:
    """Break an oversized paragraph at single-newline boundaries."""
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


def _sentence_trim(text: str) -> str:
    """
    If text does not end on a sentence boundary, trim to the last one found
    within _SENT_SEARCH chars of the end. Returns text unchanged if no
    boundary is found (e.g. financial tables, lists).
    """
    if not text:
        return text
    if text[-1] in ".!?":
        return text
    tail = text[-_SENT_SEARCH:]
    matches = list(_SENT_BOUNDARY_RE.finditer(tail))
    if not matches:
        return text
    last = matches[-1]
    # +1 to include the punctuation char itself
    cut = len(text) - _SENT_SEARCH + last.start() + 1
    return text[:cut].rstrip()


def _is_table_chunk(text: str, start_offset: int, table_offsets: set[int]) -> bool:
    """True if the chunk starts within a known table region, or looks tabular."""
    if any(abs(start_offset - off) < _TARGET_CHARS for off in table_offsets):
        return True
    table_lines = sum(1 for line in text.splitlines() if _TABLE_ROW_RE.search(line))
    return table_lines >= 3


def _pass1_sections(
    text: str,
    section_map: dict[int, str],
) -> list[_Section]:
    """
    Pass 1: split text into sections at Item boundaries.
    Uses section_map (from HTML) when available; falls back to _SECTION_RE.
    """
    sections: list[_Section] = []

    if section_map:
        breakpoints = sorted(section_map.items())  # [(offset, heading), ...]
        prev_offset = 0
        prev_item, prev_heading = None, None

        for offset, heading in breakpoints:
            if offset > prev_offset:
                sections.append(
                    _Section(
                        item_number=prev_item,
                        heading=prev_heading,
                        text=text[prev_offset:offset],
                        start_offset=prev_offset,
                    )
                )
            prev_item, prev_heading = _parse_item(heading)
            prev_offset = offset

        # Last section
        sections.append(
            _Section(
                item_number=prev_item,
                heading=prev_heading,
                text=text[prev_offset:],
                start_offset=prev_offset,
            )
        )
    else:
        # Plain-text fallback: use regex to find Item headings
        matches = list(_SECTION_RE.finditer(text))
        if not matches:
            return [_Section(item_number=None, heading=None, text=text, start_offset=0)]

        if matches[0].start() > 0:
            sections.append(
                _Section(item_number=None, heading=None, text=text[: matches[0].start()], start_offset=0)
            )

        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            item_num, heading = _parse_item(m.group(1))
            sections.append(
                _Section(
                    item_number=item_num,
                    heading=heading,
                    text=text[m.start() : end],
                    start_offset=m.start(),
                )
            )

    return [s for s in sections if s.text.strip()]


def _pass2_paragraphs(section: _Section) -> list[tuple[str, int]]:
    """
    Pass 2: split a section into paragraph-boundary chunks.
    Returns list of (chunk_text, start_offset_in_section_text).
    """
    text = re.sub(r"\r\n", "\n", section.text)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[tuple[str, int]] = []
    buffer: list[str] = []
    buffer_len = 0
    buf_start = 0  # approximate offset of buffer start within section text

    for raw_para in paragraphs:
        for para in _split_para(raw_para):
            para_len = len(para)
            if buffer and buffer_len + para_len > _TARGET_CHARS:
                chunk_text = "\n\n".join(buffer)
                chunks.append((chunk_text, section.start_offset + buf_start))
                # Overlap: carry the tail of the chunk into the next buffer
                tail = chunk_text[-_OVERLAP_CHARS:]
                buffer = [tail] if tail.strip() else []
                buffer_len = len(tail)
                buf_start = max(0, section.start_offset + buf_start + len(chunk_text) - _OVERLAP_CHARS)

            if not buffer:
                buf_start = section.start_offset
            buffer.append(para)
            buffer_len += para_len + 2

    if buffer:
        chunk_text = "\n\n".join(buffer)
        if chunk_text.strip():
            chunks.append((chunk_text, section.start_offset + buf_start))

    return chunks


def split_text(
    text: str,
    section_map: dict[int, str] | None = None,
    table_offsets: set[int] | None = None,
) -> list[RawChunk]:
    """
    Three-pass chunker:
      Pass 1 — section split (Item boundaries from section_map or regex fallback)
      Pass 2 — paragraph split within each section
      Pass 3 — sentence alignment (trim chunk ends to sentence boundaries)
    """
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if section_map is None:
        section_map = {}
    if table_offsets is None:
        table_offsets = set()

    sections = [s for s in _pass1_sections(text, section_map) if s.item_number is not None]

    chunks: list[RawChunk] = []
    chunk_index = 0

    for section in sections:
        item_number = section.item_number
        heading = section.heading
        section_label = (
            f"Item {item_number}. {heading}" if item_number and heading
            else (f"Item {item_number}." if item_number else heading)
        )

        para_chunks = _pass2_paragraphs(section)

        for raw_text, start_offset in para_chunks:
            # Pass 3: sentence alignment
            trimmed = _sentence_trim(raw_text)
            if not trimmed.strip():
                continue

            is_table = _is_table_chunk(trimmed, start_offset, table_offsets)

            chunks.append(
                RawChunk(
                    text=trimmed,
                    section=section_label,
                    item_number=item_number,
                    heading=heading,
                    is_table=is_table,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1

    return chunks
