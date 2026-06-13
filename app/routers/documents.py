"""Ingestion endpoints.

POST /companies/{ticker}/ingest  — pull + index recent 10-K/10-Q filings
GET  /filings                    — list what's indexed
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.ingest.chunk import split_text
from app.ingest.edgar import download_filing, get_cik, list_filings
from app.ingest.embed import embed_texts
from app.models import Chunk, Company, Filing

router = APIRouter(tags=["filings"])


async def _upsert_company(session: AsyncSession, info: Any) -> Company:
    """Insert or update the Company row for the given CompanyInfo."""
    company = await session.scalar(select(Company).where(Company.cik == info.cik))
    if company is None:
        company = Company(
            ticker=info.ticker,
            cik=info.cik,
            name=info.name,
            sic=info.sic,
            sic_description=info.sic_description,
            state_of_incorporation=info.state_of_incorporation,
            exchanges=info.exchanges,
            entity_type=info.entity_type,
        )
        session.add(company)
        await session.flush()
    else:
        company.name = info.name
        company.sic = info.sic
        company.sic_description = info.sic_description
        company.state_of_incorporation = info.state_of_incorporation
        company.exchanges = info.exchanges
        company.entity_type = info.entity_type
    return company


@router.post("/companies/{ticker}/ingest", status_code=202)
async def ingest_company(
    ticker: str,
    limit: int = Query(default=5, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """
    Pull and index up to `limit` NEW filings for a company.
    Fetches a larger window from EDGAR so already-indexed filings don't eat
    into the limit — re-running always makes forward progress.
    """
    ticker = ticker.upper()

    try:
        cik, _ = await get_cik(ticker)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    already_indexed = await session.scalar(
        select(func.count(Filing.id))
        .join(Company, Filing.company_id == Company.id)
        .where(Company.cik == cik)
    ) or 0
    fetch_limit = already_indexed + limit

    company_info, filing_metas = await list_filings(
        cik, ticker, form_types=["10-K", "10-Q"], limit=fetch_limit
    )

    if not filing_metas:
        return {"ticker": ticker, "ingested": 0, "skipped": 0, "message": "No filings found"}

    company = await _upsert_company(session, company_info)

    ingested = 0
    skipped = 0

    for meta in filing_metas:
        if ingested >= limit:
            break

        existing = await session.scalar(
            select(Filing.id).where(Filing.url == meta.url)
        )
        if existing:
            skipped += 1
            continue

        text = await download_filing(meta.url)

        if len(text) < 500:
            skipped += 1
            continue

        filing = Filing(
            company_id=company.id,
            form_type=meta.form_type,
            fiscal_year=meta.fiscal_year,
            url=meta.url,
            filed_at=meta.filed_at,
        )
        session.add(filing)
        await session.flush()

        raw_chunks = split_text(text)
        embeddings = await embed_texts([c.text for c in raw_chunks])

        for raw_chunk, embedding in zip(raw_chunks, embeddings):
            session.add(
                Chunk(
                    filing_id=filing.id,
                    chunk_index=raw_chunk.chunk_index,
                    section=raw_chunk.section,
                    text=raw_chunk.text,
                    embedding=embedding,
                )
            )

        await session.commit()
        ingested += 1

    return {
        "ticker": ticker,
        "company": company.name,
        "ingested": ingested,
        "skipped": skipped,
        "total_found": len(filing_metas),
    }


@router.get("/filings")
async def list_indexed_filings(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List all indexed filings."""
    rows = (
        await session.execute(
            select(
                Filing.id,
                Company.ticker,
                Company.name,
                Company.sic_description,
                Filing.form_type,
                Filing.fiscal_year,
                Filing.filed_at,
                Filing.url,
            )
            .join(Company, Filing.company_id == Company.id)
            .order_by(Company.ticker, Filing.form_type, Filing.fiscal_year.desc().nulls_last())
        )
    ).all()

    return [
        {
            "id": r.id,
            "ticker": r.ticker,
            "company": r.name,
            "sector": r.sic_description,
            "form_type": r.form_type,
            "fiscal_year": r.fiscal_year,
            "filed_at": r.filed_at.isoformat() if r.filed_at else None,
            "url": r.url,
        }
        for r in rows
    ]
