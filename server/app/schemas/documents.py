from pydantic import BaseModel, field_validator, model_validator, Field
from typing import Optional
from decimal import Decimal
from datetime import date
from enum import Enum

class DocumentType(str, Enum):
    BC = "BC"
    BL = "BL"
    FACTURE = "FACTURE"
    UNKNOWN = "UNKNOWN"

class ExtractionTier(int, Enum):
    TEMPLATE = 1
    CLOUD_OCR = 2
    LLM = 3
    HUMAN = 4


class LineItemSchema(BaseModel):
    line_number: int
    # ── Normalised / parsed values (used for matching and computation) ────────
    ref_produit: Optional[str] = None
    ref_produit_normalized: Optional[str] = None
    designation: Optional[str] = None
    qty: Optional[Decimal] = None
    unit: Optional[str] = None
    prix_unitaire: Optional[Decimal] = None
    tva_rate: Optional[Decimal] = None
    total_ligne_ht: Optional[Decimal] = None
    raw_reference: Optional[str] = None
    raw_designation: Optional[str] = None
    raw_qty: Optional[str] = None
    raw_unit_price: Optional[str] = None
    raw_total: Optional[str] = None
    line_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reference_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    designation_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    quantity_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    unit_price_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    total_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    math_consistency_ok: Optional[bool] = None
    math_consistency_ratio: Optional[float] = None 
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    field_confidence_map: dict[str, float] = Field(default_factory=dict)
    has_low_confidence: bool = False

    @model_validator(mode="after")
    def validate_line_math(self) -> "LineItemSchema":
        """
        Check qty × prix_unitaire ≈ total_ligne_ht.

        If the three values are present:
        - Record math_consistency_ok and math_consistency_ratio.
        - If inconsistent (diff > 1% of total), lower total_ligne_ht confidence
          to 0.5 and set has_low_confidence.
        - Never auto-correct any value — only flag.

        A ratio far from 1.0 (e.g. 10.0 or 0.1) hints at a decimal-point
        OCR error that the caller can investigate.
        """
        if self.qty and self.prix_unitaire and self.total_ligne_ht:
            expected = self.qty * self.prix_unitaire
            if expected != Decimal("0"):
                ratio = float(self.total_ligne_ht / expected)
                self.math_consistency_ratio = round(ratio, 4)
                diff = abs(expected - self.total_ligne_ht)
                tolerance = max(Decimal("0.02"), self.total_ligne_ht * Decimal("0.01"))
                if diff <= tolerance:
                    self.math_consistency_ok = True
                else:
                    self.math_consistency_ok = False
                    current = self.field_confidence_map.get("total_ligne_ht", 1.0)
                    self.field_confidence_map["total_ligne_ht"] = min(current, 0.5)
                    self.has_low_confidence = True
        return self


class BonDeCommandeSchema(BaseModel):
    doc_type: DocumentType = DocumentType.BC
    ref_bc: str
    document_date: Optional[date] = None
    supplier_name: Optional[str] = None
    supplier_id: Optional[str] = None
    lines: list[LineItemSchema] = Field(default_factory=list)
    total_ht: Optional[Decimal] = None
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    extraction_source_tier: ExtractionTier = ExtractionTier.TEMPLATE
    field_confidence_map: dict[str, float] = Field(default_factory=dict)
    has_low_confidence_fields: bool = False

    @field_validator("ref_bc")
    @classmethod
    def normalize_ref(cls, v: str) -> str:
        return v.strip().upper()


class BonDeLivraison(BaseModel):
    doc_type: DocumentType = DocumentType.BL
    ref_bl: str
    ref_bc_linked: Optional[str] = None
    document_date: Optional[date] = None
    supplier_name: Optional[str] = None
    lines: list[LineItemSchema] = Field(default_factory=list)
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    extraction_source_tier: ExtractionTier = ExtractionTier.TEMPLATE
    field_confidence_map: dict[str, float] = Field(default_factory=dict)
    has_low_confidence_fields: bool = False

    @field_validator("ref_bl")
    @classmethod
    def normalize_ref(cls, v: str) -> str:
        return v.strip().upper()


class FactureSchema(BaseModel):
    doc_type: DocumentType = DocumentType.FACTURE
    ref_facture: str
    ref_bc_linked: Optional[str] = None
    document_date: Optional[date] = None
    supplier_name: Optional[str] = None
    lines: list[LineItemSchema] = Field(default_factory=list)
    total_ht: Optional[Decimal] = None
    total_tva: Optional[Decimal] = None
    total_ttc: Optional[Decimal] = None
    tva_rate: Optional[Decimal] = None
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    extraction_source_tier: ExtractionTier = ExtractionTier.TEMPLATE
    field_confidence_map: dict[str, float] = Field(default_factory=dict)
    has_low_confidence_fields: bool = False

    @field_validator("ref_facture")
    @classmethod
    def normalize_ref(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def validate_totals(self) -> "FactureSchema":
        if self.total_ht and self.total_ttc and self.tva_rate:
            expected_ttc = self.total_ht * (1 + self.tva_rate / 100)
            diff = abs(expected_ttc - self.total_ttc)
            if diff > Decimal("0.05"):
                current = self.field_confidence_map.get("total_ttc", 1.0)
                self.field_confidence_map["total_ttc"] = min(current, 0.5)
                self.has_low_confidence_fields = True
        return self