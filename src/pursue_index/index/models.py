"""Postgres schema for the index.

Two-table design:
  * ``cards``  — one row per scraped card (manifest-level metadata).
  * ``pages``  — one row per OCR'd page, with ``tsvector`` for FTS.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Card(Base):
    __tablename__ = "cards"

    card_id: Mapped[str] = mapped_column(String(32), primary_key=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(8), nullable=False)
    agency: Mapped[str] = mapped_column(String(128), nullable=False)
    release_date: Mapped[str | None] = mapped_column(String(64))
    incident_date: Mapped[str | None] = mapped_column(String(64))
    incident_location: Mapped[str | None] = mapped_column(String(256))
    redacted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    asset_url: Mapped[str | None] = mapped_column(Text)
    asset_filename: Mapped[str | None] = mapped_column(Text)
    modal_image_url: Mapped[str | None] = mapped_column(Text)

    dvids_video_id: Mapped[str | None] = mapped_column(String(64))
    video_title: Mapped[str | None] = mapped_column(Text)

    pdf_pairing: Mapped[str | None] = mapped_column(Text)
    video_pairing: Mapped[str | None] = mapped_column(Text)

    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)

    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    pages: Mapped[list["Page"]] = relationship(back_populates="card", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_cards_agency", "agency"),
        Index("ix_cards_asset_type", "asset_type"),
        Index("ix_cards_redacted", "redacted"),
    )


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("cards.card_id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ocr_engine: Mapped[str] = mapped_column(String(32), nullable=False, default="tesseract")
    ocr_confidence: Mapped[float | None] = mapped_column()

    text_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(text, ''))", persisted=True),
    )

    card: Mapped[Card] = relationship(back_populates="pages")

    __table_args__ = (
        Index("ix_pages_card_page", "card_id", "page_number", unique=True),
        Index("ix_pages_text_tsv", "text_tsv", postgresql_using="gin"),
    )
