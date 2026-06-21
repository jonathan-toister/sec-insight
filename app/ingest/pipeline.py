"""Shared ingest pipeline — used by the arq worker (and formerly the REST endpoint)."""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.chunk import split_text
from app.ingest.edgar import download_filing
from app.ingest.embed import embed_texts
from app.ingest.sic import sic_to_sector_industry
from app.models import Chunk, Company, Filing


async def upsert_company(session: AsyncSession, info: Any) -> Company:
    """Insert or update the Company row for the given CompanyInfo."""
    sector, industry = sic_to_sector_industry(info.sic)
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
            sector=sector,
            industry=industry,
            fiscal_year_end=info.fiscal_year_end,
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
        company.sector = sector
        company.industry = industry
        company.fiscal_year_end = info.fiscal_year_end
    return company


async def ingest_one_filing(session: AsyncSession, meta: Any, company: Company) -> Filing | None:
    """
    Download, chunk, embed, and persist one filing.

    Returns the Filing ORM object, or None if the URL was already indexed or
    the document was too short. Does NOT commit — caller is responsible.
    """
    existing = await session.scalar(select(Filing.id).where(Filing.url == meta.url))
    if existing:
        return None

    content = await download_filing(meta.url)
    if len(content.text) < 500:
        return None

    filing = Filing(
        company_id=company.id,
        form_type=meta.form_type,
        fiscal_year=meta.fiscal_year,
        url=meta.url,
        filed_at=meta.filed_at,
        period_of_report=meta.period_of_report,
        accession_number=meta.accession_number,
        source_type="sec_filing",
    )
    session.add(filing)
    await session.flush()

    raw_chunks = split_text(content.text, content.section_map, content.table_offsets)
    embeddings = await embed_texts([c.text for c in raw_chunks])

    for raw_chunk, embedding in zip(raw_chunks, embeddings):
        session.add(
            Chunk(
                filing_id=filing.id,
                chunk_index=raw_chunk.chunk_index,
                section=raw_chunk.section,
                item_number=raw_chunk.item_number,
                heading=raw_chunk.heading,
                is_table=raw_chunk.is_table,
                fiscal_year=meta.fiscal_year,
                text=raw_chunk.text,
                embedding=embedding,
            )
        )

    await session.flush()
    return filing
