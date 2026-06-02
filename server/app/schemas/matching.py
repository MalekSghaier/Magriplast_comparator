from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class LineVerdict(str, Enum):
    MATCH         = "MATCH"
    MISMATCH      = "MISMATCH"
    MISSING       = "MISSING"
    EXTRA         = "EXTRA"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    PARTIAL_DATA  = "PARTIAL_DATA"
    PARTIAL_MATCH = "PARTIAL_MATCH"   # algorithmic score 0.50-0.79, flagged for review


class GlobalVerdict(str, Enum):
    VALIDATED  = "VALIDATED"
    PARTIAL    = "PARTIAL"
    REJECTED   = "REJECTED"
    REVIEW     = "REVIEW"
    INCOMPLETE = "INCOMPLETE"


class LineComparisonResult(BaseModel):
    ref_produit: str                          # always the BC-side reference
    ref_produit_facture: Optional[str] = None # FACTURE-side reference when matched
    ref_produit_bl: Optional[str] = None      # BL-side reference when matched
    designation: Optional[str] = None

    qty_bc:      Optional[float] = None
    qty_bl:      Optional[float] = None
    qty_facture: Optional[float] = None

    prix_bc:      Optional[float] = None
    prix_facture: Optional[float] = None

    tva_bc:      Optional[float] = None
    tva_facture: Optional[float] = None

    total_bc:      Optional[float] = None
    total_facture: Optional[float] = None

    verdict:         LineVerdict
    mismatch_fields: list[str] = []
    confidence:      float = 1.0
    notes:           Optional[str] = None

    # Matching metadata added by the multi-layer engine
    match_layer:          int  = 0    # 1-6 (0 = unmatched / default)
    field_confidence_map: dict = Field(default_factory=dict)
    reference_alias_applied: bool = False
    reference_alias_id: Optional[str] = None
    reference_alias_external: Optional[str] = None
    reference_alias_internal: Optional[str] = None
    reference_alias_supplier_key: Optional[str] = None


class MatchResultSchema(BaseModel):
    job_id:         str
    global_verdict: GlobalVerdict
    line_results:   list[LineComparisonResult]
    total_lines:    int
    match_count:    int
    mismatch_count: int
    missing_count:  int
    extra_count:    int
    low_confidence_count: int   # includes PARTIAL_MATCH + LOW_CONFIDENCE + PARTIAL_DATA
    used_fuzzy_link:            bool           = False
    bc_to_bl_link_confidence:   Optional[float] = None
    bc_to_facture_link_confidence: Optional[float] = None
