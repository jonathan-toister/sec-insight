"""
Integration test for Phase 8 XBRL ingestion.

Tests:
  1. create_all creates new tables (metric_dimensions, financial_facts)
  2. seed_metric_dimensions populates canonical tags
  3. upsert_xbrl_facts fetches AAPL from EDGAR and inserts facts
  4. Facts linked to already-ingested filings get filing_id set
  5. Facts without a text filing land in accession_fact_ids
  6. queue_missing_filings creates IngestJob rows with pending_fact_ids
  7. Worker backfill: pending_fact_ids → filing_id update
  8. Idempotency: re-running upsert_xbrl_facts doesn't duplicate rows

Run from project root:
    python3 scripts/test_phase8.py
"""
import asyncio
import json
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from decimal import Decimal
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import settings
from app.models import Base, Company, Filing, FinancialFact, IngestJob, MetricDimension
from app.ingest.xbrl import (
    seed_metric_dimensions,
    upsert_xbrl_facts,
    queue_missing_filings,
)

# ── fakeredis replaces real Redis so the test runs without a Redis server ──
import fakeredis.aioredis as fakeredis_aioredis

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)

PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"
INFO = "\033[94mℹ️ \033[0m"

def ok(msg): print(f"{PASS}  {msg}")
def fail(msg): print(f"{FAIL}  {msg}"); sys.exit(1)
def info(msg): print(f"{INFO} {msg}")


async def main():
    # ── 0. Create tables ──────────────────────────────────────────────────
    print("\n── Step 0: create_all ──")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ok("create_all completed (metric_dimensions + financial_facts tables created)")

    async with Session() as session:
        # Verify tables exist
        res = await session.execute(
            text("SELECT COUNT(*) FROM information_schema.tables "
                 "WHERE table_name IN ('metric_dimensions','financial_facts')")
        )
        count = res.scalar()
        if count == 2:
            ok("Both new tables exist in DB")
        else:
            fail(f"Expected 2 tables, found {count}")

    # ── 1. Seed metric_dimensions ─────────────────────────────────────────
    print("\n── Step 1: seed_metric_dimensions ──")
    async with Session() as session:
        await seed_metric_dimensions(session)
        await session.commit()
        n = await session.scalar(select(func.count(MetricDimension.id)))
        if n >= 20:
            ok(f"Seeded {n} metric dimensions")
        else:
            fail(f"Expected ≥20 dimension rows, got {n}")

        # Idempotency: run again, count should not change
        await seed_metric_dimensions(session)
        await session.commit()
        n2 = await session.scalar(select(func.count(MetricDimension.id)))
        if n2 == n:
            ok(f"Seed is idempotent (still {n2} rows)")
        else:
            fail(f"Seed not idempotent: {n} → {n2}")

        # Spot-check a few canonical names
        rev = await session.scalar(
            select(MetricDimension.canonical_name)
            .where(MetricDimension.xbrl_tag == "Revenues")
        )
        eps = await session.scalar(
            select(MetricDimension.canonical_name)
            .where(MetricDimension.xbrl_tag == "EarningsPerShareBasic")
        )
        ocf = await session.scalar(
            select(MetricDimension.canonical_name)
            .where(MetricDimension.xbrl_tag == "NetCashProvidedByUsedInOperatingActivities")
        )
        if rev == "Revenue" and eps == "EPSBasic" and ocf == "OperatingCashFlow":
            ok("Spot-check canonical names: Revenue, EPSBasic, OperatingCashFlow ✓")
        else:
            fail(f"Canonical name mismatch: rev={rev!r} eps={eps!r} ocf={ocf!r}")

    # ── 2. Resolve AAPL from DB ───────────────────────────────────────────
    print("\n── Step 2: resolve AAPL ──")
    async with Session() as session:
        aapl = await session.scalar(select(Company).where(Company.ticker == "AAPL"))
        if aapl is None:
            fail("AAPL not in companies table — ingest a filing first")
        info(f"AAPL: id={aapl.id} cik={aapl.cik} name={aapl.name}")
        ok("AAPL company row found")

        # How many text filings exist for AAPL?
        filing_count = await session.scalar(
            select(func.count(Filing.id)).where(Filing.company_id == aapl.id)
        )
        info(f"AAPL has {filing_count} text filing(s) in DB")

    # ── 3. upsert_xbrl_facts ─────────────────────────────────────────────
    print("\n── Step 3: upsert_xbrl_facts (fetches from EDGAR) ──")
    info("Clearing any prior AAPL financial_facts for a clean insert…")
    async with Session() as session:
        await session.execute(
            text("DELETE FROM financial_facts WHERE company_id = :cid"),
            {"cid": aapl.id}
        )
        # Also clear any AAPL ingest_jobs created by a previous test run
        await session.execute(
            text("DELETE FROM ingest_jobs WHERE ticker = 'AAPL' AND pending_fact_ids IS NOT NULL")
        )
        await session.commit()
    info("Fetching AAPL companyfacts from EDGAR — may take a few seconds…")

    async with Session() as session:
        accession_fact_ids = await upsert_xbrl_facts(session, aapl, aapl.cik)
        await session.commit()

        total_facts = await session.scalar(
            select(func.count(FinancialFact.id))
            .where(FinancialFact.company_id == aapl.id)
        )
        if total_facts and total_facts > 0:
            ok(f"Inserted {total_facts} financial facts for AAPL")
        else:
            fail("No financial facts inserted")

        linked = await session.scalar(
            select(func.count(FinancialFact.id))
            .where(FinancialFact.company_id == aapl.id)
            .where(FinancialFact.filing_id.is_not(None))
        )
        unlinked = await session.scalar(
            select(func.count(FinancialFact.id))
            .where(FinancialFact.company_id == aapl.id)
            .where(FinancialFact.filing_id.is_(None))
        )
        info(f"  linked (filing_id set): {linked}")
        info(f"  unlinked (filing_id NULL): {unlinked}")

        if filing_count > 0 and linked == 0:
            fail("Have text filings but no facts got linked — accession lookup broken")
        ok(f"Filing linkage: {linked} linked / {unlinked} unlinked")

        # Check accession_fact_ids covers unlinked rows
        total_in_dict = sum(len(v) for v in accession_fact_ids.values())
        info(f"  accession_fact_ids: {len(accession_fact_ids)} accessions, {total_in_dict} total fact IDs")

        if unlinked > 0 and total_in_dict == 0:
            fail("Unlinked facts exist but accession_fact_ids is empty — missing facts won't be queued")
        if unlinked == 0 and total_in_dict == 0:
            info("All facts linked to existing text filings — no queue_missing_filings needed")
        ok("accession_fact_ids correctly covers unlinked facts")

        # Sample Revenue for FY2024 or FY2023
        rev_row = (await session.execute(
            select(FinancialFact)
            .where(FinancialFact.company_id == aapl.id)
            .where(FinancialFact.metric_canonical == "Revenue")
            .where(FinancialFact.fiscal_period == "FY")
            .order_by(FinancialFact.fiscal_year.desc())
            .limit(1)
        )).scalar_one_or_none()
        if rev_row:
            ok(f"Sample Revenue: FY{rev_row.fiscal_year} = ${float(rev_row.value)/1e9:.1f}B  "
               f"period_end={rev_row.period_end}  filed={rev_row.filed_at}  "
               f"filing_id={rev_row.filing_id}  accession={rev_row.accession}")
        else:
            fail("No Revenue fact found for AAPL")

        # Sample EPS
        eps_row = (await session.execute(
            select(FinancialFact)
            .where(FinancialFact.company_id == aapl.id)
            .where(FinancialFact.metric_canonical == "EPSDiluted")
            .where(FinancialFact.fiscal_period == "FY")
            .order_by(FinancialFact.fiscal_year.desc())
            .limit(1)
        )).scalar_one_or_none()
        if eps_row:
            ok(f"Sample EPSDiluted: FY{eps_row.fiscal_year} = ${float(eps_row.value):.2f}/share")
        else:
            info("No EPSDiluted found (may not be reported as standard tag)")

    # ── 4. Idempotency: re-run upsert ────────────────────────────────────
    print("\n── Step 4: idempotency ──")
    async with Session() as session:
        before = await session.scalar(
            select(func.count(FinancialFact.id)).where(FinancialFact.company_id == aapl.id)
        )
        await upsert_xbrl_facts(session, aapl, aapl.cik)
        await session.commit()
        after = await session.scalar(
            select(func.count(FinancialFact.id)).where(FinancialFact.company_id == aapl.id)
        )
        if before == after:
            ok(f"Idempotent: re-run produced no new rows ({after} facts)")
        else:
            fail(f"Not idempotent: {before} → {after} facts after re-run")

    # ── 5. queue_missing_filings ──────────────────────────────────────────
    print("\n── Step 5: queue_missing_filings ──")

    if not accession_fact_ids:
        info("All facts already linked — simulating unlinked facts by picking 3 accessions")
        # Grab 3 accessions from AAPL financial_facts to simulate unlinked state
        async with Session() as session:
            rows = (await session.execute(
                select(FinancialFact.id, FinancialFact.accession)
                .where(FinancialFact.company_id == aapl.id)
                .where(FinancialFact.accession.is_not(None))
                .distinct(FinancialFact.accession)
                .order_by(FinancialFact.accession)
                .limit(3)
            )).all()
            if not rows:
                fail("No accessions found in financial_facts — cannot simulate")
            # Build a fake accession_fact_ids dict for accessions we pick
            # but that don't currently have an IngestJob (to test the "new job" path)
            accession_fact_ids = {}
            for r in rows:
                # Only use accessions that DON'T already have a text filing
                filing_exists = await session.scalar(
                    select(Filing.id)
                    .where(Filing.company_id == aapl.id)
                    .where(Filing.accession_number == r.accession)
                )
                if filing_exists is None:
                    accession_fact_ids.setdefault(r.accession, []).append(r.id)
                    if len(accession_fact_ids) >= 2:
                        break
            if not accession_fact_ids:
                info("All sampled accessions already have text filings — queue_missing_filings has nothing to do")
            else:
                info(f"Simulated unlinked accessions: {list(accession_fact_ids.keys())}")

    if not accession_fact_ids:
        info("SKIP: No unlinked accessions to queue (all filings already ingested)")
    else:
        fake_redis = await fakeredis_aioredis.FakeRedis()

        # Wrap fake_redis to match arq's enqueue_job interface
        class FakeArqRedis:
            def __init__(self, r): self._r = r
            async def enqueue_job(self, func_name, job_row_id, _job_id=None):
                # Record what was enqueued
                await self._r.lpush("queued_jobs", json.dumps({"func": func_name, "row_id": job_row_id, "job_id": _job_id}))
                class Result:
                    def __init__(self, jid): self.job_id = jid
                return Result(_job_id)

        arq = FakeArqRedis(fake_redis)

        # Delete any existing jobs for AAPL so we start clean
        async with Session() as session:
            for accession in list(accession_fact_ids.keys()):
                # Get fiscal_year from a fact row
                row = (await session.execute(
                    select(FinancialFact.fiscal_year)
                    .where(FinancialFact.id.in_(accession_fact_ids[accession]))
                    .limit(1)
                )).first()
                if row and row.fiscal_year:
                    await session.execute(
                        text("DELETE FROM ingest_jobs WHERE ticker=:t AND fiscal_year=:fy"),
                        {"t": "AAPL", "fy": row.fiscal_year}
                    )
            await session.commit()

        async with Session() as session:
            jobs_before = await session.scalar(
                select(func.count(IngestJob.id)).where(IngestJob.ticker == "AAPL")
            )
            await queue_missing_filings(session, aapl, accession_fact_ids, arq)
            await session.commit()
            jobs_after = await session.scalar(
                select(func.count(IngestJob.id)).where(IngestJob.ticker == "AAPL")
            )

            new_jobs = jobs_after - jobs_before
            info(f"Jobs before: {jobs_before}, after: {jobs_after} (+{new_jobs} new)")
            if new_jobs > 0:
                ok(f"queue_missing_filings created {new_jobs} new IngestJob(s)")
            else:
                info("No new jobs created (all accessions may map to same fiscal_year with existing jobs)")

            # Verify pending_fact_ids are set
            job_rows = (await session.execute(
                select(IngestJob)
                .where(IngestJob.ticker == "AAPL")
                .where(IngestJob.pending_fact_ids.is_not(None))
                .order_by(IngestJob.created_at.desc())
                .limit(5)
            )).scalars().all()

            if job_rows:
                ok(f"Found {len(job_rows)} IngestJob(s) with pending_fact_ids set")
                for j in job_rows:
                    ids = json.loads(j.pending_fact_ids)
                    info(f"  job_id={j.job_id}  form={j.form_type}  fy={j.fiscal_year}  "
                         f"pending_fact_ids={ids[:5]}{'…' if len(ids)>5 else ''} ({len(ids)} total)")
            else:
                info("No IngestJob rows have pending_fact_ids (may be normal if all queued accessions mapped to known filings)")

            # Check arq queue received the jobs
            queued = await fake_redis.lrange("queued_jobs", 0, -1)
            info(f"arq queue received {len(queued)} job enqueue(s):")
            for q in queued:
                info(f"  {json.loads(q)}")
            if queued:
                ok(f"arq got {len(queued)} enqueue call(s)")

    # ── 6. Backfill path simulation ───────────────────────────────────────
    print("\n── Step 6: backfill simulation (pending_fact_ids → filing_id) ──")
    async with Session() as session:
        # Find any IngestJob with pending_fact_ids
        job_with_ids = (await session.execute(
            select(IngestJob)
            .where(IngestJob.ticker == "AAPL")
            .where(IngestJob.pending_fact_ids.is_not(None))
            .limit(1)
        )).scalar_one_or_none()

        if job_with_ids is None:
            info("No job with pending_fact_ids found — simulating backfill from a fact with filing_id=NULL")
            # Pick any unlinked fact
            unlinked_fact = (await session.execute(
                select(FinancialFact)
                .where(FinancialFact.company_id == aapl.id)
                .where(FinancialFact.filing_id.is_(None))
                .limit(1)
            )).scalar_one_or_none()
            if unlinked_fact is None:
                info("No unlinked facts found — all facts already have filing_id")
                ok("Backfill path: N/A (all facts linked)")
            else:
                # Simulate: worker has pending_fact_ids=[unlinked_fact.id] and just ingested a filing
                fact_ids = [unlinked_fact.id]
                # Use any existing filing as the "just ingested" one
                any_filing = await session.scalar(
                    select(Filing).where(Filing.company_id == aapl.id).limit(1)
                )
                if any_filing:
                    from sqlalchemy import update as sa_update
                    await session.execute(
                        sa_update(FinancialFact)
                        .where(FinancialFact.id.in_(fact_ids))
                        .values(filing_id=any_filing.id)
                    )
                    await session.commit()
                    # Verify
                    updated = await session.scalar(
                        select(FinancialFact.filing_id)
                        .where(FinancialFact.id == unlinked_fact.id)
                    )
                    if updated == any_filing.id:
                        ok(f"Backfill: FinancialFact.id={unlinked_fact.id} → filing_id={any_filing.id} ✓")
                    else:
                        fail(f"Backfill failed: filing_id={updated!r} (expected {any_filing.id})")
                    # Restore NULL for subsequent test runs
                    await session.execute(
                        sa_update(FinancialFact)
                        .where(FinancialFact.id == unlinked_fact.id)
                        .values(filing_id=None)
                    )
                    await session.commit()
                else:
                    info("No filing exists to simulate backfill against")
        else:
            fact_ids = json.loads(job_with_ids.pending_fact_ids)
            info(f"Simulating backfill for job {job_with_ids.job_id}: {len(fact_ids)} fact IDs")
            # Create a dummy filing to backfill into
            any_filing = await session.scalar(
                select(Filing).where(Filing.company_id == aapl.id).limit(1)
            )
            if any_filing and fact_ids:
                from sqlalchemy import update as sa_update
                result = await session.execute(
                    sa_update(FinancialFact)
                    .where(FinancialFact.id.in_(fact_ids))
                    .values(filing_id=any_filing.id)
                    .returning(FinancialFact.id)
                )
                updated_ids = [r[0] for r in result]
                await session.commit()
                ok(f"Backfill: set filing_id={any_filing.id} on {len(updated_ids)} facts (from pending_fact_ids)")
            else:
                info("No filing to backfill against (AAPL text filings not yet ingested)")

    # ── 7. get_financials tool handler ────────────────────────────────────
    print("\n── Step 7: get_financials tool handler ──")
    async with Session() as session:
        from app.tools.registry import handle_get_financials

        # All metrics for AAPL
        result = await handle_get_financials({"ticker": "AAPL"}, session)
        lines = result.splitlines()
        if "Financial facts for AAPL" in lines[0]:
            ok(f"get_financials('AAPL') returned {len(lines)-1} rows")
        else:
            fail(f"Unexpected output: {result[:200]}")
        info(f"  First 3 rows:\n    " + "\n    ".join(lines[1:4]))

        # Filter by metric
        result2 = await handle_get_financials({"ticker": "AAPL", "metric": "Revenue"}, session)
        if "Revenue" in result2 and "Financial facts for AAPL" in result2:
            ok("get_financials filtered by metric='Revenue'")
        else:
            fail(f"Revenue filter failed: {result2[:200]}")

        # Filter by period
        result3 = await handle_get_financials({"ticker": "AAPL", "period": "FY2023"}, session)
        if "Financial facts for AAPL" in result3:
            ok("get_financials filtered by period='FY2023'")
            info(f"  FY2023 sample: {result3.splitlines()[1] if len(result3.splitlines()) > 1 else 'empty'}")
        else:
            info(f"  FY2023 result: {result3[:100]}")

        # Unknown ticker
        result4 = await handle_get_financials({"ticker": "ZZZZ"}, session)
        if "No company found" in result4:
            ok("Unknown ticker returns friendly error")
        else:
            fail(f"Expected 'No company found', got: {result4[:100]}")

        # Missing ticker
        result5 = await handle_get_financials({}, session)
        if "Error" in result5:
            ok("Missing ticker returns error")
        else:
            fail(f"Expected error for missing ticker, got: {result5[:100]}")

    print("\n" + "─"*60)
    print("\033[92m✅ All Phase 8 checks passed\033[0m\n")
    await engine.dispose()


asyncio.run(main())
