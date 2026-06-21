"""SQLAlchemy ORM models."""
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.config import settings


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticker: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    cik: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sic: Mapped[str | None] = mapped_column(Text, nullable=True)
    sic_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_of_incorporation: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchanges: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    sector: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry: Mapped[str | None] = mapped_column(Text, nullable=True)
    fiscal_year_end: Mapped[str | None] = mapped_column(Text, nullable=True)  # "MMDD"

    filings: Mapped[list["Filing"]] = relationship(back_populates="company_rel")


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (
        UniqueConstraint("url"),
        Index("ix_filings_company_period", "company_id", "period_of_report"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id"), nullable=False
    )
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    filed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_of_report: Mapped[date | None] = mapped_column(Date, nullable=True)
    accession_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="sec_filing")

    company_rel: Mapped["Company"] = relationship(back_populates="filings")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="filing")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_filing_id", "filing_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    filing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("filings.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_table: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )

    filing: Mapped["Filing"] = relationship(back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.seq"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class IngestJob(Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = (UniqueConstraint("ticker", "form_type", "fiscal_year"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # status: queued | running | done | failed
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
