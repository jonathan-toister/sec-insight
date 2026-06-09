"""Ingestion endpoints.

POST /companies/{ticker}/ingest  — pull + index recent 10-K/10-Q filings
GET  /filings                    — list what's indexed
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.ingest.chunk import split_text
from app.ingest.edgar import download_filing, get_cik, list_filings
from app.ingest.embed import embed_texts
from app.models import Chunk, Filing

router = APIRouter(tags=["filings"])


@router.post("/companies/{ticker}/ingest", status_code=202)
async def ingest_company(
    ticker: str,
    limit: int = Query(default=5, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """
    Pull and index the most recent 10-K and 10-Q filings for a company.
    Safe to re-run: already-indexed filings are skipped (deduplicated by URL).
    """
    ticker = ticker.upper()

    try:
        cik, company_name = await get_cik(ticker)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    filing_metas = await list_filings(
        cik, company_name, ticker, form_types=["10-K", "10-Q"], limit=limit
    )

    if not filing_metas:
        return {"ticker": ticker, "ingested": 0, "skipped": 0, "message": "No filings found"}

    ingested = 0
    skipped = 0

    for meta in filing_metas:
        # Dedup by URL — handles both 10-K (one/year) and 10-Q (multiple/year)
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
            cik=meta.cik,
            company=meta.company,
            ticker=meta.ticker,
            form_type=meta.form_type,
            fiscal_year=meta.fiscal_year,
            url=meta.url,
            filed_at=meta.filed_at,
        )
        session.add(filing)
        await session.flush()  # assign filing.id without committing yet

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
        "company": company_name,
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
                Filing.ticker,
                Filing.company,
                Filing.form_type,
                Filing.fiscal_year,
                Filing.filed_at,
                Filing.url,
            ).order_by(Filing.ticker, Filing.form_type, Filing.fiscal_year.desc().nulls_last())
        )
    ).all()

    return [
        {
            "id": r.id,
            "ticker": r.ticker,
            "company": r.company,
            "form_type": r.form_type,
            "fiscal_year": r.fiscal_year,
            "filed_at": r.filed_at.isoformat() if r.filed_at else None,
            "url": r.url,
        }
        for r in rows
    ]
