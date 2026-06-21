"""
Backfill Phase 7: delete all existing chunks + filings and re-ingest from scratch
using the new three-pass chunker with section_map extraction.

Run: python -m scripts.backfill_phase7

Idempotent: the URL unique constraint on filings prevents double-ingest on re-run.
Each company is processed independently; a failure in one does not abort others.
"""
import asyncio
import logging
import sys

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory
from app.ingest.edgar import list_filings as edgar_list_filings, get_cik
from app.ingest.pipeline import ingest_one_filing, upsert_company
from app.models import Chunk, Company, Filing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


async def _collect_targets(session: AsyncSession) -> list[tuple[str, str, int | None]]:
    """Return (ticker, form_type, fiscal_year) for all currently indexed filings."""
    rows = (
        await session.execute(
            select(Company.ticker, Filing.form_type, Filing.fiscal_year)
            .join(Company, Filing.company_id == Company.id)
            .order_by(Company.ticker, Filing.form_type, Filing.fiscal_year)
        )
    ).all()
    return [(r.ticker, r.form_type, r.fiscal_year) for r in rows]


async def _delete_company_filings(session: AsyncSession, ticker: str) -> int:
    """Delete all filings (and cascading chunks) for a ticker. Returns count deleted."""
    company = await session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        return 0
    result = await session.execute(
        delete(Filing).where(Filing.company_id == company.id)
    )
    await session.commit()
    return result.rowcount


async def _reingest_filing(
    session: AsyncSession,
    ticker: str,
    form_type: str,
    fiscal_year: int | None,
) -> bool:
    """
    Re-ingest a single filing. Returns True on success, False if skipped/failed.
    Skipped means URL already exists (idempotent re-run).
    """
    try:
        cik, _ = await get_cik(ticker)
    except ValueError as e:
        log.warning("  skip %s — CIK lookup failed: %s", ticker, e)
        return False

    _, filings = await edgar_list_filings(cik, ticker, form_types=[form_type], limit=20)

    target = None
    for f in filings:
        if f.form_type == form_type and (fiscal_year is None or f.fiscal_year == fiscal_year):
            target = f
            break

    if target is None:
        log.warning("  skip %s %s FY%s — not found in EDGAR", ticker, form_type, fiscal_year)
        return False

    company_info, _ = await edgar_list_filings(cik, ticker, limit=1)
    company = await upsert_company(session, company_info)

    result = await ingest_one_filing(session, target, company)
    if result is None:
        log.info("  skip %s %s FY%s — already indexed or too short", ticker, form_type, fiscal_year)
        return False

    await session.commit()
    log.info("  ingested %s %s FY%s", ticker, form_type, fiscal_year)
    return True


async def main() -> None:
    async with async_session_factory() as session:
        log.info("Collecting currently indexed filings...")
        targets = await _collect_targets(session)

    if not targets:
        log.info("No filings found — nothing to backfill.")
        return

    tickers = sorted({t for t, _, _ in targets})
    log.info("Found %d filing(s) across %d ticker(s). Targets:", len(targets), len(tickers))
    for ticker, form_type, fy in targets:
        log.info("  %s %s FY%s", ticker, form_type, fy)

    # Phase A: delete per ticker
    for ticker in tickers:
        async with async_session_factory() as session:
            n = await _delete_company_filings(session, ticker)
            log.info("Deleted %d filing(s) for %s (chunks cascade)", n, ticker)

    # Phase B: re-ingest
    success = 0
    failed = 0
    for ticker, form_type, fy in targets:
        log.info("Re-ingesting %s %s FY%s...", ticker, form_type, fy)
        async with async_session_factory() as session:
            try:
                ok = await _reingest_filing(session, ticker, form_type, fy)
                if ok:
                    success += 1
                else:
                    failed += 1
            except Exception as exc:
                log.error("  FAILED %s %s FY%s: %s", ticker, form_type, fy, exc)
                failed += 1

    log.info("Done. %d succeeded, %d skipped/failed.", success, failed)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
