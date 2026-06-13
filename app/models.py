"""SQLAlchemy ORM models."""
from datetime import date

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Date, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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

    filings: Mapped[list["Filing"]] = relationship(back_populates="company_rel")


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (UniqueConstraint("url"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id"), nullable=False
    )
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    filed_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    company_rel: Mapped["Company"] = relationship(back_populates="filings")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="filing")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    filing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("filings.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )

    filing: Mapped["Filing"] = relationship(back_populates="chunks")
