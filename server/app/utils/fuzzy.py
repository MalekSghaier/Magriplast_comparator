"""
Multi-layer fuzzy matching for OCR-degraded industrial part references.

Layer 1: Normalized exact ref match             → confidence 1.00
Layer 2: RapidFuzz ratio on normalized ref      → 0.85 (≥90) / 0.65 (≥75)
Layer 3: RapidFuzz ratio on normalized desc     → 0.75 (≥80) / 0.55 (≥60)
Layer 4: Cross-document substring / token match → 0.75
Layer 5: LLM arbitration (called in matcher)    → caller-set confidence
"""
import re
from unidecode import unidecode
from rapidfuzz import fuzz as rf_fuzz
from Levenshtein import distance as levenshtein_distance

# ── Layer 2 thresholds (on product ref) ──────────────────────────────────────
_L2_HIGH = 90.0   # ≥ 90 → high-confidence ref match
_L2_LOW  = 75.0   # 75-89 → candidate (needs price/qty bonus to confirm)

# ── Layer 3 thresholds (on description) ──────────────────────────────────────
_L3_HIGH = 80.0   # ≥ 80 → description match
_L3_LOW  = 60.0   # 60-79 → weak signal (needs price bonus to reach PARTIAL_MATCH)

# ── Base confidences returned by each layer ───────────────────────────────────
LAYER_1_CONF      = 1.00
LAYER_2_HIGH_CONF = 0.85
LAYER_2_LOW_CONF  = 0.65   # + PRICE_BONUS (0.15) → 0.80 MATCH
LAYER_3_HIGH_CONF = 0.75   # + PRICE_BONUS       → 0.90 MATCH
LAYER_3_LOW_CONF  = 0.55   # + PRICE_BONUS       → 0.70 PARTIAL_MATCH
LAYER_4_CONF      = 0.75
PRICE_BONUS = 0.05   # prices within 1 % -> small identification signal
QTY_BONUS   = 0.00   # kept for API compatibility but NOT used

# ── Final verdict thresholds ──────────────────────────────────────────────────
MATCH_THRESHOLD         = 0.80
PARTIAL_MATCH_THRESHOLD = 0.50


# ── Normalizers ───────────────────────────────────────────────────────────────

def normalize_ref(ref: str) -> str:
    """Uppercase alphanumeric only — strips spaces, hyphens, accents, slashes."""
    if not ref:
        return ""
    return re.sub(r"[^A-Z0-9]", "", ref.strip().upper())


def normalize_desc(desc: str) -> str:
    """Lowercase, remove accents via unidecode, strip punctuation."""
    if not desc:
        return ""
    return re.sub(r"[^a-z0-9 ]", "", unidecode(desc).lower()).strip()
# ── Backward-compatible helpers naflo li fil  matcher.py) ────────
def refs_match_exact(ref_a: str, ref_b: str) -> bool:
    return normalize_ref(ref_a) == normalize_ref(ref_b)
def refs_match_fuzzy(
    ref_a: str, ref_b: str, max_distance: int = 2
) -> tuple[bool, float]:
    """Returns (is_match, confidence) using Levenshtein distance on normalized refs."""
    norm_a = normalize_ref(ref_a)
    norm_b = normalize_ref(ref_b)
    if not norm_a or not norm_b:
        return False, 0.0
    if norm_a == norm_b:
        return True, 1.0
    dist = levenshtein_distance(norm_a, norm_b)
    max_len = max(len(norm_a), len(norm_b))
    if dist <= max_distance and max_len > 0:
        return True, 1.0 - (dist / max_len)
    return False, 0.0

def product_refs_match(
    ref_a: str, ref_b: str, max_distance: int = 1
) -> tuple[bool, float]:
    """Stricter product-ref variant: max_distance=1 (one OCR error allowed)."""
    return refs_match_fuzzy(ref_a, ref_b, max_distance)
# ── Multi-layer scoring ───────────────────────────────────────────────────────
def score_line_pair(
    ref_a: str,
    desc_a: str | None,
    ref_b: str,
    desc_b: str | None,
) -> tuple[float, int]:
    """
    Score two line items across all algorithmic layers (1-4).
    Returns (best_confidence, best_layer).  Layer 0 means no match found.
    Composite bonuses (price, qty) must be applied separately via apply_bonuses().
    """
    best_conf  = 0.0
    best_layer = 0

    def _update(conf: float, layer: int) -> None:
        nonlocal best_conf, best_layer
        if conf > best_conf:
            best_conf  = conf
            best_layer = layer

    nref_a = normalize_ref(ref_a or "")
    nref_b = normalize_ref(ref_b or "")
    # ── Layer 1: exact normalized ref ─────────────────────────────────────────
    if nref_a and nref_b and nref_a == nref_b:
        return LAYER_1_CONF, 1
    if nref_a and nref_b:
        tsr = rf_fuzz.token_sort_ratio(nref_a, nref_b)
        wr  = rf_fuzz.WRatio(nref_a, nref_b)
        best_ref = max(tsr, wr)
        if best_ref >= _L2_HIGH:
            _update(LAYER_2_HIGH_CONF, 2)
        elif best_ref >= _L2_LOW:
            _update(LAYER_2_LOW_CONF, 2)
    # ── Layer 3: RapidFuzz on description ────────────────────────────────────
    ndesc_a = normalize_desc(desc_a or "")
    ndesc_b = normalize_desc(desc_b or "")
    if ndesc_a and ndesc_b:
        tsr_d = rf_fuzz.token_sort_ratio(ndesc_a, ndesc_b)
        wr_d  = rf_fuzz.WRatio(ndesc_a, ndesc_b)
        best_desc = max(tsr_d, wr_d)
        if best_desc >= _L3_HIGH:
            _update(LAYER_3_HIGH_CONF, 3)
        elif best_desc >= _L3_LOW:
            _update(LAYER_3_LOW_CONF, 3)

    # ── Layer 4a: ref appears verbatim inside the other's description ─────────
    nref_from_desc_b = normalize_ref(desc_b or "")
    nref_from_desc_a = normalize_ref(desc_a or "")
    if nref_a and nref_from_desc_b and nref_a in nref_from_desc_b:
        _update(LAYER_4_CONF, 4)
    if nref_b and nref_from_desc_a and nref_b in nref_from_desc_a:
        _update(LAYER_4_CONF, 4)
    # ── Layer 4b: one normalized ref is a sub-string of the other ────────────
    if nref_a and nref_b:
        shorter = nref_a if len(nref_a) <= len(nref_b) else nref_b
        longer  = nref_b if len(nref_a) <= len(nref_b) else nref_a
        if len(shorter) >= 4 and shorter in longer:
            _update(LAYER_4_CONF, 4)
    return best_conf, best_layer


def apply_bonuses(
    base_score: float,
    prix_a: float | None,
    prix_b: float | None,
    qty_a: float | None = None,   
    qty_b: float | None = None,
    price_pct_tol: float = 0.01,
    qty_pct_tol: float = 0.05,
) -> float:
    """
    Apply identification bonuses to a base layer score.

    Only price similarity is used as a bonus. Quantity is intentionally
    excluded because partial deliveries will by design have different
    quantities and should not influence identification scoring.

    Price bonus: +0.05 when BC and doc unit prices are within `price_pct_tol`
    (default 1%). Result is capped at 1.0.
    """
    score = float(base_score or 0.0)
    if prix_a is not None and prix_b is not None:
        try:
            bc_f = float(prix_a)
            doc_f = float(prix_b)
            avg = (bc_f + doc_f) / 2.0
            if avg > 0 and abs(bc_f - doc_f) / avg <= price_pct_tol:
                score = min(score + PRICE_BONUS, 1.0)
        except (ValueError, ZeroDivisionError):
            pass
    return min(score, 1.0)
