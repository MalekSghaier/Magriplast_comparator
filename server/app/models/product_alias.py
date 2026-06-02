import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class SupplierProductAlias(Base):
    """
    Human-approved mapping from a supplier-facing product reference to the
    internal BC reference used by Magriplast.

    Matching uses aliases only inside the supplier scope and never overwrites
    extracted document values.
    """

    __tablename__ = "supplier_product_aliases"
    __table_args__ = (
        UniqueConstraint(
            "supplier_key",
            "external_ref_normalized",
            name="uq_supplier_product_alias_external",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    supplier_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("supplier_profiles.id"), nullable=True, index=True
    )
    supplier_key: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    external_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    external_ref_normalized: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    internal_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    internal_ref_normalized: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_job_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("jobs.id"), nullable=True, index=True
    )
    source_line: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    approved_by: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    supplier: Mapped["SupplierProfile"] = relationship("SupplierProfile")
