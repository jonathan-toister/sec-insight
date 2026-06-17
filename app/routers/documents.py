"""Filing metadata endpoints.

GET /filings — list all indexed filings
"""
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Company, Filing

router = APIRouter(tags=["filings"])


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
