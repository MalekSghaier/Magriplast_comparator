import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Float, Integer, Boolean, DateTime, Enum as SaEnum, UniqueConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class WordCategory(str, enum.Enum):
    PRODUCT = "PRODUCT"
    UNIT = "UNIT"
    BRAND = "BRAND"
    ACTION = "ACTION"
    MATERIAL = "MATERIAL"
    MISC = "MISC"
    DOCUMENT = "DOCUMENT"   # document type keywords: facture, bon commande, bl…
    HEADER = "HEADER"       # column/field headers: désignation, quantité, p.u.ht…
    PAYMENT = "PAYMENT"     # payment terms: chèque, traite, virement…


class WordSource(str, enum.Enum):
    MANUAL = "MANUAL"
    GPT = "GPT"
    FUZZY = "FUZZY"
    LLM_SUGGESTED = "LLM_SUGGESTED"  # GPT batch suggestion — not yet verified


class WordDictionaryEntry(Base):
    __tablename__ = "word_dictionary"
    __table_args__ = (
        UniqueConstraint("raw_form", name="uq_word_dictionary_raw_form"),
        Index("ix_word_dictionary_raw_weight", "raw_form", "weight"),
        Index("ix_word_dictionary_active", "ignored", "verified"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    raw_form: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    canonical_form: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(
        SaEnum(WordCategory, name="word_category", create_type=True),
        nullable=False,
        default=WordCategory.MISC,
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source: Mapped[str] = mapped_column(
        SaEnum(WordSource, name="word_source", create_type=True),
        nullable=False,
        default=WordSource.MANUAL,
    )
    # verified: False for LLM_SUGGESTED until confirmed; True for MANUAL/FUZZY
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ignored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supplier_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
