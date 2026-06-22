"""XBRL company facts ingestion — Phase 8."""
import asyncio
import json
import logging
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import select, update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Company, Filing, FinancialFact, IngestJob, MetricDimension

_logger = logging.getLogger(__name__)

_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_RATE_LIMIT_DELAY = 0.12
_VALID_FORMS = {"10-K", "10-Q"}
_VALID_PERIODS = {"FY", "Q1", "Q2", "Q3", "Q4"}

# Maps XBRL tag → (canonical_name, statement, sign, unit_expected)
METRIC_MAP: dict[str, tuple[str, str, int, str]] = {
    # Income statement
    "Revenues": ("Revenue", "income_statement", 1, "USD"),
    "RevenueFromContractWithCustomerExcludingAssessedTax": ("Revenue", "income_statement", 1, "USD"),
    "RevenueFromContractWithCustomerIncludingAssessedTax": ("Revenue", "income_statement", 1, "USD"),
    "SalesRevenueNet": ("Revenue", "income_statement", 1, "USD"),
    "SalesRevenueGoodsNet": ("Revenue", "income_statement", 1, "USD"),
    "GrossProfit": ("GrossProfit", "income_statement", 1, "USD"),
    "OperatingIncomeLoss": ("OperatingIncome", "income_statement", 1, "USD"),
    "NetIncomeLoss": ("NetIncome", "income_statement", 1, "USD"),
    "ProfitLoss": ("NetIncome", "income_statement", 1, "USD"),
    "EarningsPerShareBasic": ("EPSBasic", "income_statement", 1, "USD/shares"),
    "EarningsPerShareDiluted": ("EPSDiluted", "income_statement", 1, "USD/shares"),
    "InterestExpense": ("InterestExpense", "income_statement", -1, "USD"),
    "IncomeTaxExpenseBenefit": ("IncomeTaxExpense", "income_statement", -1, "USD"),
    "ResearchAndDevelopmentExpense": ("RnDExpense", "income_statement", -1, "USD"),
    # Balance sheet
    "Assets": ("TotalAssets", "balance_sheet", 1, "USD"),
    "Liabilities": ("TotalLiabilities", "balance_sheet", -1, "USD"),
    "StockholdersEquity": ("Equity", "balance_sheet", 1, "USD"),
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": ("Equity", "balance_sheet", 1, "USD"),
    "CashAndCashEquivalentsAtCarryingValue": ("Cash", "balance_sheet", 1, "USD"),
    "LongTermDebt": ("LongTermDebt", "balance_sheet", -1, "USD"),
    "CommonStockSharesOutstanding": ("SharesOutstanding", "balance_sheet", 1, "shares"),
    # Cash flow
    "NetCashProvidedByUsedInOperatingActivities": ("OperatingCashFlow", "cash_flow", 1, "USD"),
    "PaymentsToAcquirePropertyPlantAndEquipment": ("CapEx", "cash_flow", -1, "USD"),
    "DepreciationDepletionAndAmortization": ("DnA", "cash_flow", 1, "USD"),
    "DepreciationAndAmortization": ("DnA", "cash_flow", 1, "USD"),
    "Dividends": ("Dividends", "cash_flow", -1, "USD"),
    "DividendsCommonStockCash": ("Dividends", "cash_flow", -1, "USD"),
}


async def seed_metric_dimensions(session: AsyncSession) -> None:
    """Populate metric_dimensions from METRIC_MAP. Idempotent (skips existing tags)."""
    rows = [
        {
            "xbrl_tag": tag,
            "canonical_name": canonical,
            "statement": statement,
            "sign": sign,
            "unit_expected": unit,
        }
        for tag, (canonical, statement, sign, unit) in METRIC_MAP.items()
    ]
    stmt = pg_insert(MetricDimension).values(rows).on_conflict_do_nothing(index_elements=["xbrl_tag"])
    await session.execute(stmt)


async def fetch_companyfacts(cik: str) -> dict:
    """GET XBRL company facts from EDGAR."""
    url = _COMPANYFACTS_URL.format(cik=cik)
    headers = {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        await asyncio.sleep(_RATE_LIMIT_DELAY)
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def upsert_xbrl_facts(
    session: AsyncSession,
    company: Company,
    cik: str,
) -> dict[str, list[int]]:
    """Fetch EDGAR XBRL facts and upsert into financial_facts.

    Returns mapping accession → [FinancialFact.id] for rows inserted with filing_id=NULL.
    """
    data = await fetch_companyfacts(cik)

    # Load all metric dimensions into a local dict for fast lookup.
    dim_rows = (await session.execute(select(MetricDimension))).scalars().all()
    tag_to_dim: dict[str, MetricDimension] = {d.xbrl_tag: d for d in dim_rows}

    # Load known accessions for this company so we can link filing_id.
    filing_rows = (
        await session.execute(
            select(Filing.id, Filing.accession_number)
            .where(Filing.company_id == company.id)
            .where(Filing.accession_number.is_not(None))
        )
    ).all()
    accession_to_filing_id: dict[str, int] = {r.accession_number: r.id for r in filing_rows}

    us_gaap = data.get("facts", {}).get("us-gaap", {})

    to_insert: list[dict] = []

    for tag, concept in us_gaap.items():
        dim = tag_to_dim.get(tag)
        if dim is None:
            continue

        for unit_label, entries in concept.get("units", {}).items():
            for entry in entries:
                form = entry.get("form", "")
                fp = entry.get("fp", "")
                if form not in _VALID_FORMS or fp not in _VALID_PERIODS:
                    continue

                accession = entry.get("accn")
                fy = entry.get("fy")
                val = entry.get("val")
                end_str = entry.get("end")
                filed_str = entry.get("filed")

                if val is None or fy is None or accession is None:
                    continue

                period_end: date | None = None
                if end_str:
                    try:
                        period_end = date.fromisoformat(end_str)
                    except ValueError:
                        pass

                filed_at: date | None = None
                if filed_str:
                    try:
                        filed_at = date.fromisoformat(filed_str)
                    except ValueError:
                        pass

                filing_id = accession_to_filing_id.get(accession) if accession else None

                to_insert.append({
                    "company_id": company.id,
                    "filing_id": filing_id,
                    "accession": accession,
                    "fiscal_period": fp,
                    "fiscal_year": int(fy),
                    "period_end": period_end,
                    "filed_at": filed_at,
                    "metric_canonical": dim.canonical_name,
                    "xbrl_tag": tag,
                    "value": Decimal(str(val)),
                    "unit": unit_label,
                })

    if not to_insert:
        _logger.info("xbrl: no facts to insert for %s", company.ticker)
        return {}

    # Deduplicate within the batch: multiple XBRL tags can map to the same canonical
    # metric (e.g., Revenues + RevenueFromContractWithCustomer → Revenue). Keep the
    # first occurrence per unique-constraint key to avoid intra-batch conflicts.
    seen_keys: set[tuple] = set()
    deduped: list[dict] = []
    for row in to_insert:
        key = (row["company_id"], row["metric_canonical"], row["fiscal_period"], row["fiscal_year"], row["accession"])
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(row)
    to_insert = deduped

    # Batch insert, skip conflicts.
    stmt = (
        pg_insert(FinancialFact)
        .values(to_insert)
        .on_conflict_do_nothing(
            index_elements=["company_id", "metric_canonical", "fiscal_period", "fiscal_year", "accession"]
        )
        .returning(FinancialFact.id, FinancialFact.accession, FinancialFact.filing_id)
    )
    result = (await session.execute(stmt)).all()
    await session.flush()

    _logger.info("xbrl: upserted %d facts for %s", len(result), company.ticker)

    # Collect IDs of rows inserted without a filing_id.
    accession_fact_ids: dict[str, list[int]] = {}
    for row in result:
        if row.filing_id is None and row.accession:
            accession_fact_ids.setdefault(row.accession, []).append(row.id)

    return accession_fact_ids


async def queue_missing_filings(
    session: AsyncSession,
    company: Company,
    accession_fact_ids: dict[str, list[int]],
    arq_redis,
) -> None:
    """Queue ingest jobs for filings referenced by XBRL but not yet text-ingested.

    accession_fact_ids: accession → [FinancialFact.id] for rows with filing_id=NULL.
    Stores those IDs in IngestJob.pending_fact_ids so the worker can backfill without
    re-querying.
    """
    if not accession_fact_ids or arq_redis is None:
        return

    # Fetch companyfacts again is too expensive; we already have accession + fp info
    # in the financial_facts rows — re-query them to get fiscal_period/fiscal_year.
    fact_ids_all = [fid for ids in accession_fact_ids.values() for fid in ids]
    fact_rows = (
        await session.execute(
            select(
                FinancialFact.id,
                FinancialFact.accession,
                FinancialFact.fiscal_period,
                FinancialFact.fiscal_year,
            ).where(FinancialFact.id.in_(fact_ids_all))
        )
    ).all()

    # Group by (accession, fiscal_period → form_type, fiscal_year).
    # Use the first fiscal_period encountered per accession to determine form_type.
    accession_meta: dict[str, dict] = {}
    for row in fact_rows:
        if row.accession not in accession_meta:
            form_type = "10-K" if row.fiscal_period == "FY" else "10-Q"
            accession_meta[row.accession] = {
                "form_type": form_type,
                "fiscal_year": row.fiscal_year,
            }

    for accession, meta in accession_meta.items():
        ticker = company.ticker
        form_type = meta["form_type"]
        fiscal_year = meta["fiscal_year"]
        fact_ids = accession_fact_ids.get(accession, [])

        if fiscal_year is None:
            continue

        existing = await session.scalar(
            select(IngestJob)
            .where(IngestJob.ticker == ticker)
            .where(IngestJob.form_type == form_type)
            .where(IngestJob.fiscal_year == fiscal_year)
        )

        if existing and existing.status == "done":
            # Filing already ingested — look up its id and backfill directly.
            filing_id = await session.scalar(
                select(Filing.id)
                .where(Filing.company_id == company.id)
                .where(Filing.accession_number == accession)
            )
            if filing_id is not None:
                await session.execute(
                    sa_update(FinancialFact)
                    .where(FinancialFact.id.in_(fact_ids))
                    .values(filing_id=filing_id)
                )
                _logger.info(
                    "xbrl: immediate backfill filing_id=%d on %d facts (filing already done)",
                    filing_id, len(fact_ids),
                )
            continue

        if existing and existing.status in ("queued", "running"):
            # Job will complete soon — merge our fact IDs in so the backfill runs when it does.
            existing_ids: list[int] = json.loads(existing.pending_fact_ids or "[]")
            merged = list(set(existing_ids) | set(fact_ids))
            existing.pending_fact_ids = json.dumps(merged)
            _logger.info(
                "xbrl: merged %d pending_fact_ids onto existing job %s (status=%s)",
                len(fact_ids), existing.job_id, existing.status,
            )
            continue

        if existing:
            # Failed job — reset and re-enqueue with pending fact IDs.
            existing_ids = json.loads(existing.pending_fact_ids or "[]")
            merged = list(set(existing_ids) | set(fact_ids))
            existing.pending_fact_ids = json.dumps(merged)
            existing.status = "queued"
            existing.error_message = None
            existing.started_at = None
            existing.completed_at = None
            await session.flush()
            job_row_id = existing.id
        else:
            job = IngestJob(
                ticker=ticker,
                form_type=form_type,
                fiscal_year=fiscal_year,
                status="queued",
                pending_fact_ids=json.dumps(fact_ids),
            )
            session.add(job)
            await session.flush()
            job_row_id = job.id

        arq_job_id = f"ingest-{ticker}-{form_type}-{fiscal_year}-xbrl"
        arq_result = await arq_redis.enqueue_job(
            "ingest_filing_task",
            job_row_id,
            _job_id=arq_job_id,
        )
        actual_job_id = arq_result.job_id if arq_result else arq_job_id

        if existing:
            existing.job_id = actual_job_id
        else:
            job_obj = await session.get(IngestJob, job_row_id)
            if job_obj:
                job_obj.job_id = actual_job_id

        _logger.info(
            "xbrl: queued ingest for %s %s FY%s (pending_fact_ids=%d) job_id=%s",
            ticker, form_type, fiscal_year, len(fact_ids), actual_job_id,
        )
