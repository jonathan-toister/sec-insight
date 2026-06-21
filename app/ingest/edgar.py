"""SEC EDGAR client.

Pulls filings from EDGAR's free JSON/HTML endpoints. No API key required.
SEC mandates a descriptive User-Agent header and ~10 req/sec max.
"""
import asyncio
import re
from dataclasses import dataclass, field
from datetime import date

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from app.config import settings

_HEADERS = {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}
_SEC_BASE = "https://www.sec.gov"
_DATA_BASE = "https://data.sec.gov"
_REQUEST_DELAY = 0.12  # stay well under the 10 req/sec SEC limit

# Matches SEC item headings in plain text (fallback for non-HTML filings)
_SECTION_RE = re.compile(
    r"^(item\s+\d+[a-z]?\.?\s+\S.{0,80})", re.IGNORECASE | re.MULTILINE
)
# Matches all-caps bold-style headings (≥3 uppercase words)
_ALLCAPS_RE = re.compile(r"^(?:[A-Z][A-Z0-9&,\-\s]{1,}){3,}$")


@dataclass
class FilingContent:
    text: str
    section_map: dict[int, str] = field(default_factory=dict)   # char_offset -> heading
    table_offsets: set[int] = field(default_factory=set)         # char offsets of table starts


@dataclass
class CompanyInfo:
    cik: str
    ticker: str
    name: str
    sic: str | None
    sic_description: str | None
    state_of_incorporation: str | None
    exchanges: str | None  # comma-separated
    entity_type: str | None
    fiscal_year_end: str | None  # "MMDD" e.g. "1231"; None if EDGAR has no value


@dataclass
class FilingMeta:
    form_type: str
    fiscal_year: int | None
    url: str
    filed_at: date | None
    period_of_report: date | None  # fiscal period the document covers
    accession_number: str | None   # dashes-included, e.g. "0000320193-24-000123"


async def get_cik(ticker: str) -> tuple[str, str]:
    """
    Resolve a ticker to its EDGAR CIK (zero-padded to 10 digits).
    Returns (cik, company_name). Raises ValueError if not found.
    """
    async with httpx.AsyncClient(headers=_HEADERS, timeout=15) as client:
        resp = await client.get(f"{_SEC_BASE}/files/company_tickers.json")
        resp.raise_for_status()

    ticker_upper = ticker.upper()
    for entry in resp.json().values():
        if entry["ticker"].upper() == ticker_upper:
            cik = str(entry["cik_str"]).zfill(10)
            return cik, entry["title"]

    raise ValueError(f"Ticker {ticker!r} not found in EDGAR company list")


async def list_filings(
    cik: str,
    ticker: str,
    form_types: list[str] | None = None,
    limit: int = 5,
) -> tuple[CompanyInfo, list[FilingMeta]]:
    """
    Fetch company info and recent filings from the EDGAR submissions API.
    Returns (CompanyInfo, filings) — up to `limit` filings, newest first.
    """
    if form_types is None:
        form_types = ["10-K", "10-Q"]

    await asyncio.sleep(_REQUEST_DELAY)
    async with httpx.AsyncClient(headers=_HEADERS, timeout=15) as client:
        resp = await client.get(f"{_DATA_BASE}/submissions/CIK{cik}.json")
        resp.raise_for_status()

    data = resp.json()

    exchanges_list: list[str] = data.get("exchanges", []) or []
    company_info = CompanyInfo(
        cik=cik,
        ticker=ticker,
        name=data.get("name", ""),
        sic=str(data["sic"]) if data.get("sic") else None,
        sic_description=data.get("sicDescription") or None,
        state_of_incorporation=data.get("stateOfIncorporation") or None,
        exchanges=",".join(exchanges_list) if exchanges_list else None,
        entity_type=data.get("entityType") or None,
        fiscal_year_end=data.get("fiscalYearEnd") or None,
    )

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    results: list[FilingMeta] = []
    for i, form in enumerate(forms):
        if form not in form_types:
            continue

        accession_path = accessions[i].replace("-", "")
        primary_doc = primary_docs[i]
        cik_int = int(cik)
        url = f"{_SEC_BASE}/Archives/edgar/data/{cik_int}/{accession_path}/{primary_doc}"

        fiscal_year: int | None = None
        period_of_report: date | None = None
        if i < len(report_dates) and report_dates[i]:
            try:
                fiscal_year = int(report_dates[i][:4])
                period_of_report = date.fromisoformat(report_dates[i])
            except (ValueError, IndexError):
                pass

        filed_at: date | None = None
        if i < len(filing_dates) and filing_dates[i]:
            try:
                filed_at = date.fromisoformat(filing_dates[i])
            except ValueError:
                pass

        results.append(
            FilingMeta(
                form_type=form,
                fiscal_year=fiscal_year,
                url=url,
                filed_at=filed_at,
                period_of_report=period_of_report,
                accession_number=accessions[i] if i < len(accessions) else None,
            )
        )

        if len(results) >= limit:
            break

    return company_info, results


def _extract_section_map(soup: BeautifulSoup, full_text: str) -> tuple[dict[int, str], set[int]]:
    """
    Walk a parsed HTML soup tree to build:
      - section_map: char offset in full_text → heading text (for Item headings)
      - table_offsets: char offsets where <table> content begins

    Heading candidates: <h1>–<h4>, <b>/<strong> containing an Item pattern or all-caps text.
    Only headings that match SEC Item patterns are recorded; decorative bolds are skipped.
    """
    section_map: dict[int, str] = {}
    table_offsets: set[int] = set()

    heading_tags = {"h1", "h2", "h3", "h4"}

    def _is_item_heading(text: str) -> bool:
        t = text.strip()
        return bool(_SECTION_RE.match(t)) or bool(_ALLCAPS_RE.match(t))

    def _find_offset(needle: str) -> int | None:
        """Return the first char offset of needle in full_text, or None."""
        idx = full_text.find(needle)
        return idx if idx != -1 else None

    for element in soup.find_all(True):
        tag_name = element.name.lower() if element.name else ""

        if tag_name in heading_tags:
            raw = element.get_text(" ", strip=True)
            if raw and _is_item_heading(raw):
                offset = _find_offset(raw[:60])  # use prefix for robustness
                if offset is not None:
                    section_map[offset] = raw

        elif tag_name in ("b", "strong"):
            raw = element.get_text(" ", strip=True)
            # Only short bolds that look like Item headings (avoid tagging whole paragraphs)
            if raw and len(raw) < 120 and _is_item_heading(raw):
                offset = _find_offset(raw[:60])
                if offset is not None:
                    section_map[offset] = raw

        elif tag_name == "table":
            table_text = element.get_text(" ", strip=True)
            if table_text:
                offset = _find_offset(table_text[:60])
                if offset is not None:
                    table_offsets.add(offset)

    return section_map, table_offsets


async def download_filing(url: str) -> FilingContent:
    """
    Download a filing document and return a FilingContent with:
      - cleaned plain text
      - section_map (char offset → heading) extracted from HTML structure
      - table_offsets (char offsets of table starts)

    Falls back to empty section_map for plain-text submissions.
    """
    await asyncio.sleep(_REQUEST_DELAY)
    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=60, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        raw = resp.text

    section_map: dict[int, str] = {}
    table_offsets: set[int] = set()

    if "html" in content_type.lower() or raw.lstrip().startswith("<"):
        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(["script", "style", "head"]):
            tag.decompose()
        text = soup.get_text(separator="\n")

        # Normalize before building map so offsets match what the chunker sees
        lines = [line.rstrip() for line in text.splitlines()]
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

        section_map, table_offsets = _extract_section_map(soup, text)
    else:
        text = raw
        lines = [line.rstrip() for line in text.splitlines()]
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

    return FilingContent(text=text, section_map=section_map, table_offsets=table_offsets)
