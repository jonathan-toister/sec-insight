#!/usr/bin/env python
"""Backfill Phase 6 fields for already-ingested rows.

Pass 1: sector, industry, fiscal_year_end on companies.
Pass 2: period_of_report, accession_number on filings.

Safe to re-run (idempotent — skips rows that already have the values).
Run from the project root: python scripts/backfill_phase6.py
"""
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.ingest.edgar import list_filings as edgar_list_filings
from app.ingest.sic import sic_to_sector_industry
from app.models import Company, Filing

log = logging.getLogger(__name__)


async def backfill_companies(session: AsyncSession) -> None:
    rows = (
        await session.scalars(
            select(Company).where(
                (Company.sector.is_(None))
                | (Company.fiscal_year_end.is_(None))
            )
        )
    ).all()

    log.info("Pass 1: %d companies need backfill", len(rows))
    for company in rows:
        try:
            sector, industry = sic_to_sector_industry(company.sic)
            company.sector = sector
            company.industry = industry

            if company.fiscal_year_end is None:
                info, _ = await edgar_list_filings(company.cik, company.ticker, limit=1)
                company.fiscal_year_end = info.fiscal_year_end

            await session.commit()
            log.info("  %s — sector=%s fiscal_year_end=%s", company.ticker, sector, company.fiscal_year_end)
        except Exception:
            await session.rollback()
            log.exception("  %s — failed, skipping", company.ticker)


def _accession_from_url(url: str) -> str | None:
    """Extract the dashes-included accession number from an EDGAR filing URL."""
    try:
        # URL: .../Archives/edgar/data/{cik}/{18-char-no-dashes}/{doc}
        after_data = url.split("/Archives/edgar/data/")[1]
        raw = after_data.split("/")[1]  # 18-char segment, no dashes
        if len(raw) == 18 and raw.isdigit():
            return f"{raw[:10]}-{raw[10:12]}-{raw[12:]}"
    except (IndexError, ValueError):
        pass
    return None


async def backfill_filings(session: AsyncSession) -> None:
    filings = (
        await session.scalars(
            select(Filing).where(
                (Filing.period_of_report.is_(None))
                | (Filing.accession_number.is_(None))
            )
        )
    ).all()

    if not filings:
        log.info("Pass 2: nothing to backfill")
        return

    # Group by company_id to minimise EDGAR calls.
    from collections import defaultdict
    by_company: dict[int, list[Filing]] = defaultdict(list)
    for f in filings:
        by_company[f.company_id].append(f)

    log.info("Pass 2: %d filings across %d companies need backfill", len(filings), len(by_company))

    company_rows = (
        await session.scalars(
            select(Company).where(Company.id.in_(list(by_company.keys())))
        )
    ).all()
    company_map = {c.id: c for c in company_rows}

    for company_id, db_filings in by_company.items():
        company = company_map.get(company_id)
        if not company:
            log.warning("  company_id=%d not found, skipping", company_id)
            continue
        try:
            # Collect distinct form types present in the DB filings.
            form_types = list({f.form_type for f in db_filings})
            _, edgar_filings = await edgar_list_filings(
                company.cik, company.ticker, form_types=form_types, limit=50
            )

            # Build a lookup from no-dashes accession → FilingMeta.
            edgar_by_acc: dict[str, object] = {}
            for meta in edgar_filings:
                if meta.accession_number:
                    key = meta.accession_number.replace("-", "")
                    edgar_by_acc[key] = meta

            for db_filing in db_filings:
                acc = db_filing.accession_number
                if acc is None:
                    acc = _accession_from_url(db_filing.url)
                    if acc:
                        db_filing.accession_number = acc

                if db_filing.period_of_report is None and acc:
                    meta = edgar_by_acc.get(acc.replace("-", ""))
                    if meta and meta.period_of_report:
                        db_filing.period_of_report = meta.period_of_report

            await session.commit()
            log.info("  %s — updated %d filings", company.ticker, len(db_filings))
        except Exception:
            await session.rollback()
            log.exception("  %s — failed, skipping", company.ticker)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await backfill_companies(session)
    async with AsyncSessionLocal() as session:
        await backfill_filings(session)
    log.info("Backfill complete.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(main())
