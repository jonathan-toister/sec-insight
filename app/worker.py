"""arq worker — runs as a separate process alongside the API.

Start with:  arq app.worker.WorkerSettings
"""
import json
import logging
from datetime import UTC, datetime

from arq.connections import RedisSettings
from sqlalchemy import update

from app.config import settings
from app.db import AsyncSessionLocal
from app.ingest.edgar import get_cik, list_filings as edgar_list_filings
from app.ingest.pipeline import ingest_one_filing, upsert_company
from app.ingest.xbrl import queue_missing_filings, seed_metric_dimensions, upsert_xbrl_facts
from app.models import FinancialFact, IngestJob

_logger = logging.getLogger(__name__)


async def ingest_filing_task(ctx: dict, job_row_id: int) -> None:
    """Fetch a filing from EDGAR, chunk, embed, and persist it to Postgres."""
    _logger.info("ingest_filing_task started job_row_id=%d", job_row_id)

    # Mark running in its own short transaction so status is visible immediately.
    async with AsyncSessionLocal() as session:
        job = await session.get(IngestJob, job_row_id)
        if job is None:
            _logger.warning("IngestJob %d not found — skipping", job_row_id)
            return
        job.status = "running"
        job.started_at = datetime.now(UTC)
        pending_fact_ids: list[int] = json.loads(job.pending_fact_ids or "[]")
        await session.commit()

    arq_redis = ctx.get("redis")

    error: Exception | None = None
    try:
        async with AsyncSessionLocal() as session:
            job = await session.get(IngestJob, job_row_id)
            cik, _ = await get_cik(job.ticker)
            company_info, filing_metas = await edgar_list_filings(
                cik, job.ticker, [job.form_type], limit=50
            )

            meta = next(
                (f for f in filing_metas if f.fiscal_year == job.fiscal_year), None
            )
            if meta is None:
                raise ValueError(
                    f"No {job.form_type} with fiscal_year={job.fiscal_year} found on "
                    f"EDGAR for {job.ticker}"
                )

            company = await upsert_company(session, company_info)
            filing = await ingest_one_filing(session, meta, company)
            await session.commit()

            if filing is None:
                _logger.info(
                    "ingest_filing_task job_row_id=%d: already indexed or doc too short",
                    job_row_id,
                )
            else:
                _logger.info(
                    "ingest_filing_task job_row_id=%d: ingested filing_id=%d",
                    job_row_id,
                    filing.id,
                )

            # XBRL ingestion — runs once per company, covers all historical periods.
            await seed_metric_dimensions(session)
            accession_fact_ids = await upsert_xbrl_facts(session, company, cik)
            await session.commit()

            # Backfill filing_id on facts that were waiting for this exact filing.
            if filing is not None and pending_fact_ids:
                await session.execute(
                    update(FinancialFact)
                    .where(FinancialFact.id.in_(pending_fact_ids))
                    .values(filing_id=filing.id)
                )
                await session.commit()
                _logger.info(
                    "xbrl: backfilled filing_id=%d on %d financial_facts",
                    filing.id, len(pending_fact_ids),
                )

            # Queue ingest jobs for any filings referenced by XBRL but not yet ingested.
            if accession_fact_ids:
                await queue_missing_filings(session, company, accession_fact_ids, arq_redis)
                await session.commit()

    except Exception as exc:
        error = exc
        _logger.exception("ingest_filing_task job_row_id=%d failed: %s", job_row_id, exc)

    # Final status update in a clean session regardless of success/failure.
    async with AsyncSessionLocal() as session:
        job = await session.get(IngestJob, job_row_id)
        if job:
            job.status = "done" if error is None else "failed"
            job.completed_at = datetime.now(UTC)
            if error is not None:
                job.error_message = str(error)[:2000]
            await session.commit()

    if error is not None:
        raise error


async def startup(ctx: dict) -> None:
    pass


async def shutdown(ctx: dict) -> None:
    from app.db import engine
    await engine.dispose()


class WorkerSettings:
    functions = [ingest_filing_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 4
    job_timeout = 600  # 10 minutes max per filing
