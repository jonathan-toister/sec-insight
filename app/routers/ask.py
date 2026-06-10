"""Query endpoint — POST /ask."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.ingest.embed import embed_texts
from app.rag.generate import generate_answer
from app.rag.hyde import generate_hypothetical_document
from app.rag.retrieve import retrieve
from app.schemas import AskRequest, AskResponse

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("", response_model=AskResponse)
async def ask(
    request: AskRequest,
    session: AsyncSession = Depends(get_session),
) -> AskResponse:
    """
    Answer an investor question about indexed SEC filings.

    Pipeline:
      1. HyDE: generate a hypothetical filing passage from the question (Claude)
      2. Embed: embed the hypothetical passage (OpenAI)
      3. Retrieve: vector search against the chunks table (pgvector cosine distance)
      4. Generate: build grounded answer with citations (Claude)
    """
    hypothetical_doc = await generate_hypothetical_document(request.question)

    embeddings = await embed_texts([hypothetical_doc])
    query_embedding = embeddings[0]

    chunks = await retrieve(
        embedding=query_embedding,
        session=session,
        filters=request.filters,
        k=request.k,
    )

    answer, sources, highlights_map = await generate_answer(
        question=request.question,
        chunks=chunks,
    )

    chunks_with_highlights = [
        chunk.model_copy(update={"highlights": highlights_map.get(i + 1, [])})
        for i, chunk in enumerate(chunks)
    ]

    return AskResponse(
        answer=answer,
        sources=sources,
        chunks=chunks_with_highlights,
        hypothetical_document=hypothetical_doc,
    )
