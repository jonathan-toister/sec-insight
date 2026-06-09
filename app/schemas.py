"""Pydantic request/response schemas for the API."""
from pydantic import BaseModel, Field


class FilingFilter(BaseModel):
    ticker: str | None = None
    form_type: str | None = None
    fiscal_year: int | None = None


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    filters: FilingFilter = Field(default_factory=FilingFilter)
    k: int = Field(default=6, ge=1, le=20)


class ChunkResult(BaseModel):
    chunk_id: int
    filing_id: int
    company: str
    ticker: str | None
    form_type: str
    fiscal_year: int | None
    section: str | None
    text: str
    distance: float


class AskResponse(BaseModel):
    answer: str
    sources: list[str]
    chunks: list[ChunkResult]
    hypothetical_document: str
