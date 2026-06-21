"""Pydantic request/response schemas for the API."""
from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    conversation_id: int | None = None


class ChunkResult(BaseModel):
    chunk_id: int
    filing_id: int
    company: str
    ticker: str | None
    form_type: str
    fiscal_year: int | None
    section: str | None
    item_number: str | None = None
    heading: str | None = None
    text: str
    distance: float
    highlights: list[str] = Field(default_factory=list)


class AskResponse(BaseModel):
    answer: str
    sources: list[str]
    chunks: list[ChunkResult]
    conversation_id: int
    hypothetical_document: str | None = None
