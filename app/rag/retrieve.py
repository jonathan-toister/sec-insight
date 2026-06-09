"""Vector retrieval over the chunks table (pgvector)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Filing
from app.schemas import ChunkResult, FilingFilter


async def retrieve(
    embedding: list[float],
    session: AsyncSession,
    filters: FilingFilter | None = None,
    k: int = 6,
) -> list[ChunkResult]:
    """
    Find the k most similar chunks to `embedding` using pgvector cosine distance.
    Joins with the filings table to return full citation metadata in one query.
    """
    stmt = (
        select(
            Chunk.id,
            Chunk.filing_id,
            Chunk.section,
            Chunk.text,
            Filing.company,
            Filing.ticker,
            Filing.form_type,
            Filing.fiscal_year,
            Chunk.embedding.cosine_distance(embedding).label("distance"),
        )
        .join(Filing, Chunk.filing_id == Filing.id)
        .where(Chunk.embedding.is_not(None))
        .order_by(Chunk.embedding.cosine_distance(embedding))
        .limit(k)
    )

    if filters:
        if filters.ticker:
            stmt = stmt.where(Filing.ticker == filters.ticker)
        if filters.form_type:
            stmt = stmt.where(Filing.form_type == filters.form_type)
        if filters.fiscal_year:
            stmt = stmt.where(Filing.fiscal_year == filters.fiscal_year)

    rows = (await session.execute(stmt)).all()

    return [
        ChunkResult(
            chunk_id=row.id,
            filing_id=row.filing_id,
            company=row.company,
            ticker=row.ticker,
            form_type=row.form_type,
            fiscal_year=row.fiscal_year,
            section=row.section,
            text=row.text,
            distance=float(row.distance),
        )
        for row in rows
    ]
