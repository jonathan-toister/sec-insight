"""SEC EDGAR client.

Pulls filings from EDGAR's free JSON/HTML endpoints. No API key required.
SEC mandates a descriptive User-Agent header and ~10 req/sec max.
"""
import asyncio
import re
from dataclasses import dataclass
from datetime import date

import httpx
from bs4 import BeautifulSoup

from app.config import settings

_HEADERS = {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}
_SEC_BASE = "https://www.sec.gov"
_DATA_BASE = "https://data.sec.gov"
_REQUEST_DELAY = 0.12  # stay well under the 10 req/sec SEC limit


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


@dataclass
class FilingMeta:
    form_type: str
    fiscal_year: int | None
    url: str
    filed_at: date | None


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
        if i < len(report_dates) and report_dates[i]:
            try:
                fiscal_year = int(report_dates[i][:4])
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
            )
        )

        if len(results) >= limit:
            break

    return company_info, results


async def download_filing(url: str) -> str:
    """
    Download a filing document and return its cleaned plain text.
    Handles both HTML filings and plain-text submissions.
    """
    await asyncio.sleep(_REQUEST_DELAY)
    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=60, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        raw = resp.text

    if "html" in content_type.lower() or raw.lstrip().startswith("<"):
        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(["script", "style", "head"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
    else:
        text = raw

    # Normalize: strip trailing whitespace per line, collapse blank lines
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
