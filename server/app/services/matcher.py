"""
3-Way Matching Engine — multi-layer fuzzy strategy with Hungarian optimal assignment.
Compares BC ↔ BL ↔ FACTURE line by line.

Matching layers (per line pair):
  6. Human-approved supplier product alias
  1. Normalized exact ref match
  2. RapidFuzz ratio on normalized ref (≥90 high / ≥75 candidate)
  3. RapidFuzz ratio on normalized description (≥80 high / ≥60 weak)
  4. Cross-document substring / token match
  5. LLM arbitration (OpenAI) for scores in the 0.50-0.79 ambiguous zone

Global assignment uses the Hungarian algorithm (scipy.optimize.linear_sum_assignment)
for optimal one-to-one pairing when multiple candidates exist.
"""
import json
import httpx
import numpy as np
from decimal import Decimal
from dataclasses import dataclass, field
from scipy.optimize import linear_sum_assignment
from app.schemas.documents import (
    BonDeCommandeSchema, BonDeLivraison, FactureSchema, LineItemSchema,
)
from app.schemas.matching import (
    LineVerdict, GlobalVerdict, LineComparisonResult, MatchResultSchema,
)
from app.utils.fuzzy import (
    refs_match_exact, refs_match_fuzzy, normalize_ref,
    score_line_pair, apply_bonuses,
    MATCH_THRESHOLD, PARTIAL_MATCH_THRESHOLD,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.services.reference_aliases import ReferenceAlias
logger = get_logger(__name__)


@dataclass
class MatchContext:
    job_id: str
    price_tolerance: Decimal = field(
        default_factory=lambda: Decimal(str(settings.price_tolerance))
    )
    qty_tolerance: Decimal = field(
        default_factory=lambda: Decimal(str(settings.quantity_tolerance))
    )
    tva_tolerance: Decimal = field(
        default_factory=lambda: Decimal(str(settings.tva_tolerance))
    )
    line_total_tolerance: Decimal = field(
        default_factory=lambda: Decimal(str(settings.line_total_tolerance))
    )


@dataclass(frozen=True)
class MatchAssignment:
    doc_idx: int
    confidence: float
    layer: int
    alias: ReferenceAlias | None = None


def _decimal(val) -> Decimal | None:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _within_tolerance(
    a: Decimal | None, b: Decimal | None, tolerance: Decimal
) -> bool:
    """Pure numeric comparison with tolerance. None values never match."""
    if a is None or b is None:
        return False
    return abs(a - b) <= tolerance


def _compare_quantities(
    qty_bc: Decimal,
    qty_bl_or_fac: Decimal,
    tolerance: Decimal,
    allow_partial: bool = True,
) -> tuple[bool, str | None]:
    """
    Directional quantity comparison for 3-way matching.

    Returns (is_ok, warning_code | None).

    Rules:
    - Exact match within tolerance → OK, no warning.
    - BL qty < BC qty (under-delivery) → OK when allow_partial=True.
      Partial delivery is a normal business event; the remaining qty
      will arrive in a future BL. Flag as PARTIAL_DELIVERY, not MISMATCH.
    - BL qty > BC qty by more than tolerance → OVER_DELIVERY warning.
      Suspicious but not a hard reject — may be a supplier rounding issue.
    - FACTURE qty must match BC qty exactly (within tolerance) — no partial.
    """
    if abs(qty_bc - qty_bl_or_fac) <= tolerance:
        return True, None
    if allow_partial and qty_bl_or_fac < qty_bc:
        return True, "PARTIAL_DELIVERY"
    if qty_bl_or_fac > qty_bc + tolerance:
        if not allow_partial:
            return False, "QTY_MISMATCH"
        return True, "OVER_DELIVERY"
    return False, "QTY_MISMATCH"


# ── Document-level link verification (unchanged logic) ────────────────────────

def link_documents(
    bc: BonDeCommandeSchema,
    bl: BonDeLivraison | None,
    facture: FactureSchema | None,
    ctx: MatchContext,
) -> dict:
    """
    Verify document links via reference numbers.
    Returns: { bc_bl_linked, bc_facture_linked, bc_bl_confidence,
                bc_facture_confidence, used_fuzzy, link_warnings }
    """
    result = {
        "bc_bl_linked":       False,
        "bc_facture_linked":  False,
        "bc_bl_confidence":   None,
        "bc_facture_confidence": None,
        "used_fuzzy":         False,
        "link_warnings":      [],
    }

    if bl:
        if bl.ref_bc_linked:
            if refs_match_exact(bc.ref_bc, bl.ref_bc_linked):
                result["bc_bl_linked"]     = True
                result["bc_bl_confidence"] = 1.0
            else:
                matched, conf = refs_match_fuzzy(
                    bc.ref_bc, bl.ref_bc_linked,
                    settings.reference_levenshtein_max_distance,
                )
                if matched:
                    result["bc_bl_linked"]     = True
                    result["bc_bl_confidence"] = conf
                    result["used_fuzzy"]       = True
                    result["link_warnings"].append(
                        f"BC-BL fuzzy link: '{bc.ref_bc}' ≈ '{bl.ref_bc_linked}' "
                        f"(confidence={conf:.2f})"
                    )
                else:
                    result["link_warnings"].append(
                        f"BC ref '{bc.ref_bc}' does not match BL's linked ref "
                        f"'{bl.ref_bc_linked}'"
                    )
        else:
            result["bc_bl_linked"]     = True
            result["bc_bl_confidence"] = 0.70
            result["link_warnings"].append(
                "BL has no ref_bc_linked — link assumed by document position"
            )

    if facture:
        if facture.ref_bc_linked:
            if refs_match_exact(bc.ref_bc, facture.ref_bc_linked):
                result["bc_facture_linked"]     = True
                result["bc_facture_confidence"] = 1.0
            else:
                matched, conf = refs_match_fuzzy(
                    bc.ref_bc, facture.ref_bc_linked,
                    settings.reference_levenshtein_max_distance,
                )
                if matched:
                    result["bc_facture_linked"]     = True
                    result["bc_facture_confidence"] = conf
                    result["used_fuzzy"]            = True
                    result["link_warnings"].append(
                        f"BC-FACTURE fuzzy link: '{bc.ref_bc}' ≈ "
                        f"'{facture.ref_bc_linked}' (confidence={conf:.2f})"
                    )
                else:
                    result["link_warnings"].append(
                        f"BC ref '{bc.ref_bc}' does not match FACTURE's linked ref "
                        f"'{facture.ref_bc_linked}'"
                    )
        else:
            result["bc_facture_linked"]     = True
            result["bc_facture_confidence"] = 0.70
            result["link_warnings"].append(
                "FACTURE has no ref_bc_linked — link assumed by document position"
            )

    return result


# ── Hungarian optimal assignment ──────────────────────────────────────────────

def _build_assignment(
    bc_lines: list[LineItemSchema],
    doc_lines: list[LineItemSchema],
    reference_aliases: dict[str, ReferenceAlias] | None = None,
) -> dict[int, MatchAssignment]:
    """
    Optimal one-to-one assignment of BC lines to doc lines via Hungarian algorithm.
    Returns {bc_idx: MatchAssignment}.
    Only includes pairs where composite confidence ≥ PARTIAL_MATCH_THRESHOLD (0.50).
    """
    if not bc_lines or not doc_lines:
        return {}

    n_bc  = len(bc_lines)
    n_doc = len(doc_lines)
    score_mat = np.zeros((n_bc, n_doc), dtype=float)
    layer_mat = np.zeros((n_bc, n_doc), dtype=int)
    alias_mat: list[list[ReferenceAlias | None]] = [
        [None for _ in range(n_doc)] for _ in range(n_bc)
    ]

    for i, bc in enumerate(bc_lines):
        for j, doc in enumerate(doc_lines):
            alias = None
            base, layer = 0.0, 0
            if reference_aliases:
                doc_ref_norm = normalize_ref(doc.ref_produit or "")
                bc_ref_norm = normalize_ref(bc.ref_produit or "")
                candidate_alias = reference_aliases.get(doc_ref_norm)
                if (
                    candidate_alias is not None
                    and candidate_alias.internal_ref_normalized == bc_ref_norm
                ):
                    base = 1.0
                    layer = 6
                    alias = candidate_alias
            if alias is None:
                base, layer = score_line_pair(
                    bc.ref_produit  or "",
                    bc.designation  or "",
                    doc.ref_produit or "",
                    doc.designation or "",
                )
            final = apply_bonuses(
                base,
                bc.prix_unitaire  if bc.prix_unitaire  else None,
                doc.prix_unitaire if doc.prix_unitaire else None,
                bc.qty  if bc.qty  else None,
                doc.qty if doc.qty else None,
            )
            score_mat[i, j] = final
            layer_mat[i, j] = layer
            alias_mat[i][j] = alias

    # Minimize cost = maximize confidence
    row_ind, col_ind = linear_sum_assignment(1.0 - score_mat)
    result: dict[int, MatchAssignment] = {}
    for bc_idx, doc_idx in zip(row_ind, col_ind):
        conf = float(score_mat[bc_idx, doc_idx])
        if conf >= PARTIAL_MATCH_THRESHOLD:
            result[int(bc_idx)] = MatchAssignment(
                doc_idx=int(doc_idx),
                confidence=conf,
                layer=int(layer_mat[bc_idx, doc_idx]),
                alias=alias_mat[int(bc_idx)][int(doc_idx)],
            )

    return result


def _aggregate_bl_lines(
    bl_list: list[BonDeLivraison],
) -> list[LineItemSchema]:
    """
    Merge line items from multiple BL documents into a single aggregated list.
    Lines with the same normalized ref_produit have their quantities summed so
    the matcher compares total delivered qty against BC qty.

    Lines with no ref_produit are kept as-is (cannot be merged). The lowest
    per-field confidence across merged lines is propagated so a low-confidence
    OCR reading on any delivery note is surfaced.
    """
    merged: dict[str, LineItemSchema] = {}
    for bl in bl_list:
        for line in bl.lines:
            key = (line.ref_produit_normalized or "").upper().strip()
            if not key:
                key = f"__no_ref_{id(line)}"
                merged[key] = line
                continue
            if key not in merged:
                merged[key] = line.model_copy(deep=True)
            else:
                existing = merged[key]
                if existing.qty is not None and line.qty is not None:
                    existing.qty = existing.qty + line.qty
                elif line.qty is not None:
                    existing.qty = line.qty
                existing.extraction_confidence = min(
                    existing.extraction_confidence,
                    line.extraction_confidence,
                )
                existing.has_low_confidence = (
                    existing.has_low_confidence or line.has_low_confidence
                )

    return list(merged.values())


# ── Layer 5: LLM arbitration for ambiguous pairs ──────────────────────────────

async def _llm_arbitrate(
    ref_bc: str,
    desc_bc: str,
    prix_bc: float | None,
    ref_doc: str,
    desc_doc: str,
    prix_doc: float | None,
    job_id: str,
) -> tuple[bool, float]:
    """
    Ask OpenAI whether two line items represent the same product.
    Only called when the algorithmic score is in the PARTIAL_MATCH zone (0.50-0.79).
    Returns (same_product, llm_confidence).
    Falls back to (False, 0.0) if the API key is absent or the call fails.
    """
    if not settings.openai_api_key:
        return False, 0.0

    prompt = (
        "Do these two document lines refer to the same product?\n"
        f"BC:  ref={ref_bc!r}, desc={desc_bc!r}, price={prix_bc}\n"
        f"DOC: ref={ref_doc!r}, desc={desc_doc!r}, price={prix_doc}\n"
        'Answer JSON only: {"same_product": true/false, '
        '"confidence": 0.0-1.0, "reason": "..."}'
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 150,
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return bool(parsed.get("same_product", False)), float(
                parsed.get("confidence", 0.0)
            )
    except Exception as exc:
        logger.warning("llm_arbitration_failed job_id=%s error=%s", job_id, str(exc))
        return False, 0.0

# ── Per-line field comparison ─────────────────────────────────────────────────
def _detect_and_correct_decimal_shift(
    prix_bc: Decimal | None,
    prix_fac: Decimal | None,
) -> tuple[Decimal | None, bool]:
    """
    Detect OCR decimal-shift errors in the extracted FAC price, using the
    BC price as the reliable anchor.
    Checks 10×, 100×, 1000× scale factors with 5% tolerance.
    Examples:
      prix_bc=240.278, prix_fac=24.028  → ratio≈10  → corrected to 240.280
      prix_bc=122.341, prix_fac=1.223   → ratio≈100 → corrected to 122.300
    Returns (corrected_prix_fac, was_corrected).
    Only corrects when the scale discrepancy is unambiguous (within 5% of
    a clean power-of-10 factor).  Never corrects small differences that
    fall within normal rounding — those go through the normal tolerance check.
    """
    if prix_bc is None or prix_fac is None or prix_fac == 0:
        return prix_fac, False
    ratio = float(prix_bc) / float(prix_fac)
    for factor in (10, 100, 1000):
        if abs(ratio - factor) / factor < 0.05:
            return prix_fac * Decimal(str(factor)), True
    return prix_fac, False


def _line_total_from_qty_price(line: LineItemSchema) -> Decimal | None:
    qty = _decimal(line.qty)
    price = _decimal(line.prix_unitaire)
    if qty is None or price is None:
        return None
    return qty * price


def _declared_line_total(line: LineItemSchema) -> Decimal | None:
    return _decimal(line.total_ligne_ht)


def _current_line_total(line: LineItemSchema) -> Decimal | None:
    declared = _declared_line_total(line)
    if declared is not None:
        return declared
    return _line_total_from_qty_price(line)


def _total_tolerance(ctx: MatchContext, *values: Decimal | None) -> Decimal:
    magnitudes = [abs(v) for v in values if v is not None]
    tolerance = max(ctx.line_total_tolerance, Decimal("0.100"))
    if magnitudes:
        tolerance = max(tolerance, max(magnitudes) * Decimal("0.001"))
    return tolerance


def _totals_within_tolerance(
    a: Decimal | None,
    b: Decimal | None,
    ctx: MatchContext,
) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= _total_tolerance(ctx, a, b)


def _copy_facture_values_from_bc(
    bc_line: LineItemSchema,
    facture_line: LineItemSchema,
) -> LineItemSchema:
    bc_total = _line_total_from_qty_price(bc_line)
    field_confidence_map = dict(facture_line.field_confidence_map or {})
    field_confidence_map["qty"] = min(float(field_confidence_map.get("qty", 1.0)), 0.85)
    field_confidence_map["prix_unitaire"] = min(
        float(field_confidence_map.get("prix_unitaire", 1.0)),
        0.85,
    )
    return facture_line.model_copy(
        deep=True,
        update={
            "qty": bc_line.qty,
            "prix_unitaire": bc_line.prix_unitaire,
            "total_ligne_ht": facture_line.total_ligne_ht or bc_total,
            "quantity_confidence": min(facture_line.quantity_confidence, 0.85),
            "unit_price_confidence": min(facture_line.unit_price_confidence, 0.85),
            "extraction_confidence": min(facture_line.extraction_confidence, 0.85),
            "field_confidence_map": field_confidence_map,
        },
    )


def _reconcile_facture_line_against_bc(
    bc_line: LineItemSchema,
    facture_line: LineItemSchema,
    ctx: MatchContext,
    *,
    force_document_total_reconciliation: bool = False,
) -> tuple[LineItemSchema, str | None]:
    """
    Correct obvious FAC OCR/LLM quantity or decimal slips using independent totals.
    This never trusts the BC blindly. A correction is only allowed when:
    - the FAC declared line total equals the BC expected line total, but the
      extracted FAC qty x price does not equal the FAC line total; or
    - document-level total reconciliation has already proved the FAC extracted
      qty/price set is inconsistent while the BC totals match the invoice total.
    """
    bc_total = _line_total_from_qty_price(bc_line)
    if bc_total is None:
        return facture_line, None

    declared_fac_total = _declared_line_total(facture_line)
    fac_arithmetic_total = _line_total_from_qty_price(facture_line)

    if (
        declared_fac_total is not None
        and _totals_within_tolerance(declared_fac_total, bc_total, ctx)
        and (
            fac_arithmetic_total is None
            or not _totals_within_tolerance(fac_arithmetic_total, declared_fac_total, ctx)
        )
    ):
        return (
            _copy_facture_values_from_bc(bc_line, facture_line),
            "FACTURE qty/price reconciled from invoice line total",
        )

    if force_document_total_reconciliation and (
        fac_arithmetic_total is None
        or not _totals_within_tolerance(fac_arithmetic_total, bc_total, ctx)
    ):
        return (
            _copy_facture_values_from_bc(bc_line, facture_line),
            "FACTURE qty/price reconciled from invoice total",
        )

    return facture_line, None


def _should_reconcile_facture_from_document_total(
    bc_lines: list[LineItemSchema],
    fac_lines: list[LineItemSchema],
    fac_assignment: dict[int, MatchAssignment],
    facture: FactureSchema | None,
    ctx: MatchContext,
) -> bool:
    target_total = _decimal(facture.total_ht) if facture else None
    if target_total is None or not fac_lines or not fac_assignment:
        return False
    fac_to_bc: dict[int, int] = {
        int(assignment.doc_idx): int(bc_idx)
        for bc_idx, assignment in fac_assignment.items()
    }
    current_sum = Decimal("0")
    candidate_sum = Decimal("0")
    changed_candidates = 0
    for fac_idx, fac_line in enumerate(fac_lines):
        current_total = _current_line_total(fac_line)
        if current_total is None:
            return False
        current_sum += current_total
        candidate_total = current_total
        bc_idx = fac_to_bc.get(fac_idx)
        if bc_idx is not None and 0 <= bc_idx < len(bc_lines):
            bc_total = _line_total_from_qty_price(bc_lines[bc_idx])
            if bc_total is not None:
                candidate_total = bc_total
                if not _totals_within_tolerance(current_total, bc_total, ctx):
                    changed_candidates += 1
        candidate_sum += candidate_total
    if changed_candidates == 0:
        return False
    tolerance = _total_tolerance(ctx, target_total, candidate_sum)
    current_delta = abs(current_sum - target_total)
    candidate_delta = abs(candidate_sum - target_total)
    return (
        candidate_delta <= tolerance
        and current_delta > tolerance
        and candidate_delta + tolerance < current_delta
    )


def _rate_tolerance(ctx: MatchContext) -> Decimal:
    return max(ctx.tva_tolerance, Decimal("0.25"))


def _rates_match(
    a: Decimal | None,
    b: Decimal | None,
    ctx: MatchContext,
) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= _rate_tolerance(ctx)


def _is_plausible_tva_rate(rate: Decimal | None) -> bool:
    return rate is not None and Decimal("0") <= rate <= Decimal("30")


def _is_likely_tva_ocr_slip(
    observed: Decimal | None,
    trusted: Decimal | None,
    ctx: MatchContext,
) -> bool:
    if not _is_plausible_tva_rate(observed) or not _is_plausible_tva_rate(trusted):
        return False
    if _rates_match(observed, trusted, ctx):
        return True
    diff = abs(observed - trusted)
    if diff > Decimal("4"):
        return False
    return int(observed // Decimal("10")) == int(trusted // Decimal("10"))


def _dominant_tva_rate(lines: list[LineItemSchema]) -> Decimal | None:
    counts: dict[Decimal, int] = {}
    for line in lines:
        rate = _decimal(line.tva_rate)
        if not _is_plausible_tva_rate(rate):
            continue
        key = rate.quantize(Decimal("0.01"))
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    rate, count = max(counts.items(), key=lambda item: item[1])
    total = sum(counts.values())
    if count >= 2 and Decimal(count) / Decimal(total) >= Decimal("0.60"):
        return rate
    return None


def _trusted_facture_tva_rate(facture: FactureSchema | None) -> Decimal | None:
    if not facture:
        return None
    dominant_line_rate = _dominant_tva_rate(list(facture.lines))
    if dominant_line_rate is not None:
        return dominant_line_rate
    document_rate = _decimal(facture.tva_rate)
    if _is_plausible_tva_rate(document_rate):
        return document_rate
    return None


def _reconcile_tva_rates_for_comparison(
    tva_bc: Decimal | None,
    tva_fac: Decimal | None,
    trusted_facture_tva_rate: Decimal | None,
    ctx: MatchContext,
) -> tuple[Decimal | None, Decimal | None, str | None]:
    if tva_bc is None or tva_fac is None:
        return tva_bc, tva_fac, None
    if _rates_match(tva_bc, tva_fac, ctx):
        return tva_bc, tva_fac, None
    if trusted_facture_tva_rate is None:
        return tva_bc, tva_fac, None
    if _rates_match(tva_fac, trusted_facture_tva_rate, ctx) and _is_likely_tva_ocr_slip(
        tva_bc,
        trusted_facture_tva_rate,
        ctx,
    ):
        return (
            trusted_facture_tva_rate,
            trusted_facture_tva_rate,
            "BC TVA reconciled from facture TVA consensus",
        )

    if _rates_match(tva_bc, trusted_facture_tva_rate, ctx) and _is_likely_tva_ocr_slip(
        tva_fac,
        trusted_facture_tva_rate,
        ctx,
    ):
        return (
            trusted_facture_tva_rate,
            trusted_facture_tva_rate,
            "FACTURE TVA reconciled from facture TVA consensus",
        )

    return tva_bc, tva_fac, None


def match_line_item(
    bc_line: LineItemSchema,
    bl_line: LineItemSchema | None,
    facture_line: LineItemSchema | None,
    ctx: MatchContext,
    match_confidence: float = 1.0,
    match_layer: int = 1,
    reference_alias: ReferenceAlias | None = None,
    force_facture_reconciliation: bool = False,
    trusted_facture_tva_rate: Decimal | None = None,
) -> LineComparisonResult:
    """
    Compare one BC line against its BL and FACTURE counterparts.
    match_confidence and match_layer come from the multi-layer scoring engine.
    """
    mismatch_fields: list[str] = []
    reconciliation_notes: list[str] = []
    extraction_conf = min(
        bc_line.extraction_confidence,
        bl_line.extraction_confidence      if bl_line      else 1.0,
        facture_line.extraction_confidence if facture_line else 1.0,
    )
    if facture_line:
        facture_line, reconciliation_note = _reconcile_facture_line_against_bc(
            bc_line,
            facture_line,
            ctx,
            force_document_total_reconciliation=force_facture_reconciliation,
        )
        if reconciliation_note:
            reconciliation_notes.append(reconciliation_note)

    ref = bc_line.ref_produit or bc_line.designation or f"line_{bc_line.line_number}"
    qty_bc  = _decimal(bc_line.qty)
    qty_bl  = _decimal(bl_line.qty)       if bl_line      else None
    qty_fac = _decimal(facture_line.qty)  if facture_line else None
    qty_warnings: list[str] = list(reconciliation_notes)
    if reference_alias is not None:
        extraction_conf = max(extraction_conf, 0.80)
        qty_warnings.append(
            "Reference alias applied: "
            f"{reference_alias.external_ref} -> {reference_alias.internal_ref}"
        )

    if bl_line and qty_bc and qty_bl:
        ok, warning = _compare_quantities(
            qty_bc,
            qty_bl,
            ctx.qty_tolerance,
            allow_partial=True,
        )
        if not ok:
            mismatch_fields.append("qty_bc_vs_bl")
        elif warning:
            qty_warnings.append(f"BL: {warning}")
    if facture_line and qty_bc and qty_fac:
        ok, warning = _compare_quantities(
            qty_bc,
            qty_fac,
            ctx.qty_tolerance,
            allow_partial=True,
        )
        if not ok:
            mismatch_fields.append("qty_bc_vs_facture")
        elif warning:
            qty_warnings.append(f"FACTURE: {warning}")
    prix_bc  = _decimal(bc_line.prix_unitaire)
    prix_fac = _decimal(facture_line.prix_unitaire) if facture_line else None
    if prix_bc and prix_fac:
        corrected, price_shift_corrected = _detect_and_correct_decimal_shift(prix_bc, prix_fac)
        if price_shift_corrected:
            prix_fac = corrected
            extraction_conf = min(extraction_conf, 0.65)
    if facture_line and prix_bc and prix_fac:
        effective_tolerance = max(ctx.price_tolerance, Decimal("0.100"))
        if not _within_tolerance(prix_bc, prix_fac, effective_tolerance):
            mismatch_fields.append("prix_unitaire")
    tva_bc  = _decimal(bc_line.tva_rate)
    tva_fac = _decimal(facture_line.tva_rate) if facture_line else None
    tva_bc, tva_fac, tva_reconciliation_note = _reconcile_tva_rates_for_comparison(
        tva_bc,
        tva_fac,
        trusted_facture_tva_rate,
        ctx,
    )
    if tva_reconciliation_note:
        qty_warnings.append(tva_reconciliation_note)
    if facture_line and tva_bc and tva_fac:
        if not _rates_match(tva_bc, tva_fac, ctx):
            mismatch_fields.append("tva_rate")
    is_partial_delivery = any("PARTIAL_DELIVERY" in w for w in qty_warnings)

    if not bl_line and not facture_line:
        verdict = LineVerdict.PARTIAL_DATA
    elif mismatch_fields:
        verdict = LineVerdict.MISMATCH
    elif is_partial_delivery:
        verdict = LineVerdict.PARTIAL_MATCH
    elif match_confidence < MATCH_THRESHOLD:
        if match_confidence < 0.65 or extraction_conf < 0.70:
            verdict = LineVerdict.LOW_CONFIDENCE
        else:
            verdict = LineVerdict.MATCH
    elif extraction_conf < 0.70:
        verdict = LineVerdict.LOW_CONFIDENCE
    else:
        verdict = LineVerdict.MATCH
    field_confidence_map: dict = {
        "ref_produit": round(match_confidence, 3),
        "designation": round(match_confidence, 3),
    }
    if facture_line:
        field_confidence_map["prix_unitaire"] = (
            0.0 if "prix_unitaire" in mismatch_fields else 1.0
        )
        field_confidence_map["tva_rate"] = (
            0.0 if "tva_rate" in mismatch_fields else 1.0
        )
    overall_conf = min(extraction_conf, match_confidence)
    return LineComparisonResult(
        ref_produit=ref,
        ref_produit_facture=facture_line.ref_produit if facture_line else None,
        ref_produit_bl=bl_line.ref_produit if bl_line else None,
        designation=bc_line.designation,
        qty_bc=float(qty_bc)   if qty_bc   else None,
        qty_bl=float(qty_bl)   if qty_bl   else None,
        qty_facture=float(qty_fac) if qty_fac else None,
        prix_bc=float(prix_bc) if prix_bc  else None,
        prix_facture=float(prix_fac) if prix_fac else None,
        tva_bc=float(tva_bc)   if tva_bc   else None,
        tva_facture=float(tva_fac) if tva_fac else None,
        verdict=verdict,
        mismatch_fields=mismatch_fields,
        confidence=overall_conf,
        match_layer=match_layer,
        field_confidence_map=field_confidence_map,
        notes="; ".join(qty_warnings) if qty_warnings else None,
        reference_alias_applied=reference_alias is not None,
        reference_alias_id=reference_alias.id if reference_alias else None,
        reference_alias_external=reference_alias.external_ref if reference_alias else None,
        reference_alias_internal=reference_alias.internal_ref if reference_alias else None,
        reference_alias_supplier_key=(
            reference_alias.supplier_key if reference_alias else None
        ),
    )


# ── Main entry point ──────────────────────────────────────────────────────────
async def run_three_way_match(
    bc: BonDeCommandeSchema,
    bl: list[BonDeLivraison] | BonDeLivraison | None,
    facture: FactureSchema | None,
    job_id: str,
    supplier_price_tolerance: float | None = None,
    supplier_qty_tolerance: float | None = None,
    reference_aliases: dict[str, ReferenceAlias] | None = None,
) -> MatchResultSchema:
    """
    Main entry point for 3-way matching.
    bl may be a single BonDeLivraison (backwards-compatible), a list of them
    (multi-shipment), or None. When multiple BLs are supplied, their line
    quantities are aggregated by product ref before comparison so that
    partial deliveries across several delivery notes are correctly evaluated
    against the full BC ordered quantity.
    """
    ctx = MatchContext(job_id=job_id)
    if supplier_price_tolerance is not None:
        ctx.price_tolerance = Decimal(str(supplier_price_tolerance))
    if supplier_qty_tolerance is not None:
        ctx.qty_tolerance   = Decimal(str(supplier_qty_tolerance))
    if bl is None:
        bl_list: list[BonDeLivraison] = []
    elif isinstance(bl, list):
        bl_list = bl
    else:
        bl_list = [bl]
    aggregated_bl_lines = _aggregate_bl_lines(bl_list) if bl_list else []
    bl_for_links = bl_list[0] if bl_list else None
    links = link_documents(bc, bl_for_links, facture, ctx)
    bc_lines  = list(bc.lines)
    bl_lines  = list(aggregated_bl_lines)
    fac_lines = list(facture.lines) if facture else []
    bl_assignment: dict[int, MatchAssignment] = {}
    if bl_lines:
        bl_assignment = _build_assignment(
            bc_lines,
            bl_lines,
            reference_aliases=reference_aliases,
        )
    fac_assignment: dict[int, MatchAssignment] = {}
    if fac_lines:
        fac_assignment = _build_assignment(
            bc_lines,
            fac_lines,
            reference_aliases=reference_aliases,
        )
    reconcile_facture_from_document_total = _should_reconcile_facture_from_document_total(
        bc_lines,
        fac_lines,
        fac_assignment,
        facture,
        ctx,
    )
    trusted_tva_rate = _trusted_facture_tva_rate(facture)
    matched_bl_indices:  set[int] = set()
    matched_fac_indices: set[int] = set()
    line_results: list[LineComparisonResult] = []
    for i, bc_line in enumerate(bc_lines):
        bl_assigned  = bl_assignment.get(i)
        fac_assigned = fac_assignment.get(i)
        if not bl_lines and fac_assigned is None:
            ref = bc_line.ref_produit or bc_line.designation or f"line_{bc_line.line_number}"
            line_results.append(LineComparisonResult(
                ref_produit=ref,
                designation=bc_line.designation,
                qty_bc=float(bc_line.qty)            if bc_line.qty            else None,
                prix_bc=float(bc_line.prix_unitaire) if bc_line.prix_unitaire  else None,
                tva_bc=float(bc_line.tva_rate)       if bc_line.tva_rate       else None,
                verdict=LineVerdict.MISSING,
                mismatch_fields=[],
                confidence=1.0,
                match_layer=0,
                notes="Ordered in BC but absent from FACTURE",
            ))
            continue

        if bl_lines and bl_assigned is None and fac_assigned is None:
            ref = bc_line.ref_produit_normalized or f"line_{bc_line.line_number}"
            line_results.append(LineComparisonResult(
                ref_produit=ref,
                designation=bc_line.designation,
                qty_bc=float(bc_line.qty)          if bc_line.qty          else None,
                prix_bc=float(bc_line.prix_unitaire) if bc_line.prix_unitaire else None,
                verdict=LineVerdict.MISSING,
                mismatch_fields=["ref_produit"],
                confidence=1.0,
                match_layer=0,
                notes="Product in BC not found in BL or FACTURE",
            ))
            continue
        bl_line  = bl_lines[bl_assigned.doc_idx]   if bl_assigned  else None
        fac_line = fac_lines[fac_assigned.doc_idx] if fac_assigned else None

        if bl_assigned:
            matched_bl_indices.add(bl_assigned.doc_idx)
        if fac_assigned:
            matched_fac_indices.add(fac_assigned.doc_idx)
        available = [v for v in (bl_assigned, fac_assigned) if v is not None]
        if available:
            best_assign = max(available, key=lambda x: x.confidence)
            match_conf  = best_assign.confidence
            match_layer = best_assign.layer
            reference_alias = best_assign.alias
        else:
            match_conf  = 1.0
            match_layer = 0
            reference_alias = None

        # Step 4a — Layer 5: LLM arbitration for ambiguous FACTURE matches
        if (
            fac_line
            and PARTIAL_MATCH_THRESHOLD <= match_conf < MATCH_THRESHOLD
        ):
            same, llm_conf = await _llm_arbitrate(
                ref_bc=bc_line.ref_produit   or "",
                desc_bc=bc_line.designation  or "",
                prix_bc=float(bc_line.prix_unitaire) if bc_line.prix_unitaire else None,
                ref_doc=fac_line.ref_produit  or "",
                desc_doc=fac_line.designation or "",
                prix_doc=float(fac_line.prix_unitaire) if fac_line.prix_unitaire else None,
                job_id=job_id,
            )
            if same and llm_conf >= 0.70:
                match_conf  = max(match_conf, llm_conf)
                match_layer = 5

        result = match_line_item(
            bc_line,
            bl_line,
            fac_line,
            ctx,
            match_conf,
            match_layer,
            reference_alias=reference_alias,
            force_facture_reconciliation=reconcile_facture_from_document_total,
            trusted_facture_tva_rate=trusted_tva_rate,
        )
        line_results.append(result)

    # Step 5: Detect EXTRA lines in BL not matched to any BC line
    for j, bl_line in enumerate(bl_lines):
        if j not in matched_bl_indices:
            if not bl_line.ref_produit and not bl_line.prix_unitaire:
                continue  # dimension/description artifact, not a real product line
            line_results.append(LineComparisonResult(
                ref_produit=bl_lines[j].ref_produit_normalized or f"bl_extra_{j}",
                ref_produit_bl=bl_lines[j].ref_produit,
                designation=bl_lines[j].designation,
                qty_bl=float(bl_lines[j].qty) if bl_lines[j].qty else None,
                verdict=LineVerdict.EXTRA,
                mismatch_fields=["ref_produit"],
                confidence=1.0,
                match_layer=0,
                notes="Product in BL not found in BC",
            ))

    # Step 6: Detect EXTRA lines in FACTURE not matched to any BC line
    for j, fac_line in enumerate(fac_lines):
        if j not in matched_fac_indices:
            line_results.append(LineComparisonResult(
                ref_produit=fac_lines[j].ref_produit_normalized or f"fac_extra_{j}",
                ref_produit_facture=fac_lines[j].ref_produit,
                designation=fac_lines[j].designation,
                qty_facture=float(fac_lines[j].qty) if fac_lines[j].qty else None,
                prix_facture=(
                    float(fac_lines[j].prix_unitaire)
                    if fac_lines[j].prix_unitaire else None
                ),
                verdict=LineVerdict.EXTRA,
                mismatch_fields=["ref_produit"],
                confidence=1.0,
                match_layer=0,
                notes="Product in FACTURE not found in BC",
            ))

    # Step 7: Aggregate counts and compute global verdict
    counts: dict[LineVerdict, int] = {v: 0 for v in LineVerdict}
    for r in line_results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    layer_dist: dict[str, int] = {}
    for r in line_results:
        key = f"layer_{r.match_layer}"
        layer_dist[key] = layer_dist.get(key, 0) + 1
    global_verdict = _compute_global_verdict(
        counts=counts,
        has_bl=bool(bl_lines),
        has_facture=facture is not None,
        link_warnings=links["link_warnings"],
    )


    low_conf_total = (
        counts[LineVerdict.LOW_CONFIDENCE]
        + counts[LineVerdict.PARTIAL_DATA]
        + counts[LineVerdict.PARTIAL_MATCH]
    )

    return MatchResultSchema(
        job_id=job_id,
        global_verdict=global_verdict,
        line_results=line_results,
        total_lines=len(line_results),
        match_count=counts[LineVerdict.MATCH],
        mismatch_count=counts[LineVerdict.MISMATCH],
        missing_count=counts[LineVerdict.MISSING],
        extra_count=counts[LineVerdict.EXTRA],
        low_confidence_count=low_conf_total,
        used_fuzzy_link=links["used_fuzzy"],
        bc_to_bl_link_confidence=links["bc_bl_confidence"],
        bc_to_facture_link_confidence=links["bc_facture_confidence"],
    )


# ──compute fi le5er w flagit any lines fihom chek lel user bech ya3ml revew thabet fil forntend lazemha can handele this fi display  ────────────────────────────────────────────────

def _compute_global_verdict(
    counts: dict,
    has_bl: bool,
    has_facture: bool,
    link_warnings: list[str],
) -> GlobalVerdict:
    """Deterministic global verdict from line-level counts."""
    if not has_facture:
        return GlobalVerdict.INCOMPLETE
    if counts.get(LineVerdict.MISMATCH, 0) > 0:
        return GlobalVerdict.REJECTED
    if counts.get(LineVerdict.PARTIAL_MATCH, 0) > 0:
        return GlobalVerdict.REVIEW
    if counts.get(LineVerdict.LOW_CONFIDENCE, 0) > 0:
        return GlobalVerdict.REVIEW
    if counts.get(LineVerdict.MISSING, 0) > 0:
        return GlobalVerdict.PARTIAL
    if counts.get(LineVerdict.EXTRA, 0) > 0:
        return GlobalVerdict.REVIEW
    if link_warnings:
        return GlobalVerdict.REVIEW
    return GlobalVerdict.VALIDATED
