"""Query endpoint — POST /ask."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import verify_api_key
from app.db import get_session
from app.models import Conversation, Message
from app.rag.generate import run_agent
from app.schemas import AskRequest, AskResponse

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("", response_model=AskResponse, dependencies=[Depends(verify_api_key)])
async def ask(
    http_request: Request,
    request: AskRequest,
    session: AsyncSession = Depends(get_session),
) -> AskResponse:
    """
    Answer an investor question about indexed SEC filings.

    Pass conversation_id to continue a prior conversation; omit to start a new one.
    """
    prior_messages: list[dict] = []
    conversation: Conversation | None = None

    if request.conversation_id is not None:
        result = await session.execute(
            select(Conversation)
            .where(Conversation.id == request.conversation_id)
            .options(selectinload(Conversation.messages))
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        for msg in conversation.messages:
            prior_messages.append({"role": msg.role, "content": msg.content})

    if conversation is None:
        conversation = Conversation(title=request.question[:200])
        session.add(conversation)
        await session.flush()  # get conversation.id before inserting messages

    next_seq = len(prior_messages)

    session.add(Message(
        conversation_id=conversation.id,
        seq=next_seq,
        role="user",
        content=request.question,
    ))

    arq_redis = getattr(http_request.app.state, "arq_redis", None)

    answer, sources, highlights_map, chunks, usage = await run_agent(
        request.question,
        session,
        prior_messages,
        conversation_id=conversation.id,
        arq_redis=arq_redis,
    )

    session.add(Message(
        conversation_id=conversation.id,
        seq=next_seq + 1,
        role="assistant",
        content=answer,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        cache_read_tokens=usage.get("cache_read_tokens"),
        cache_write_tokens=usage.get("cache_write_tokens"),
        model=usage.get("model"),
        latency_ms=usage.get("latency_ms"),
    ))
    await session.commit()

    chunks_with_highlights = [
        chunk.model_copy(update={"highlights": highlights_map.get(i + 1, [])})
        for i, chunk in enumerate(chunks)
    ]

    return AskResponse(
        answer=answer,
        sources=sources,
        chunks=chunks_with_highlights,
        conversation_id=conversation.id,
        hypothetical_document=None,
    )
