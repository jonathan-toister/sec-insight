"""Query endpoint — POST /ask."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.rag.generate import run_agent
from app.schemas import AskRequest, AskResponse

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("", response_model=AskResponse)
async def ask(
    request: AskRequest,
    session: AsyncSession = Depends(get_session),
) -> AskResponse:
    """
    Answer an investor question about indexed SEC filings.

    The model decides when to call search_filings, validates the results,
    and formats a grounded, cited answer. Conversational messages return
    a friendly reply with no citations.
    """
    answer, sources, highlights_map, chunks = await run_agent(request.question, session)

    chunks_with_highlights = [
        chunk.model_copy(update={"highlights": highlights_map.get(i + 1, [])})
        for i, chunk in enumerate(chunks)
    ]

    return AskResponse(
        answer=answer,
        sources=sources,
        chunks=chunks_with_highlights,
        hypothetical_document=None,
    )
