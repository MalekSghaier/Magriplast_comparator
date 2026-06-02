import re
import json
import httpx
from decimal import Decimal
from app.schemas.documents import (
    BonDeCommandeSchema, BonDeLivraison, FactureSchema,
    LineItemSchema, DocumentType, ExtractionTier
)
from app.services.page_grouper import DocumentGroup
from app.services.normalizer import (
    normalize_reference, normalize_number, normalize_date, normalize_text
)
from app.services.adaptive_dictionary import word_dictionary
from app.utils.number_parser import parse_quantity, parse_money
from app.utils.spatial_ocr import extract_spatial_rows, SpatialRow
from app.services.supplier_service import SupplierProfile, get_supplier_from_text
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# — imported lazily 
_DetectedSupplierProfile = None


# ─────────────────────────────────────────────────────────────────────────────
# TIER 1: Template-Based Extraction
# ─────────────────────────────────────────────────────────────────────────────

# Regex
_HEADER_PATTERNS = {
    "ref_bc": [
        r"(?:N[°o]?\s*(?:BC|BON\s*DE\s*COMMANDE))\s*[:\-]?\s*([A-Z0-9\-/]{3,30})",
        r"(?:COMMANDE\s*N[°o]?)\s*[:\-]?\s*([A-Z0-9\-/]{3,30})",
        r"(BC[-/]\d{2,4}[-/]\d{2,8})",
    ],
    "ref_bl": [
        r"(?:N[°o]?\s*(?:BL|BON\s*DE\s*LIVRAISON))\s*[:\-]?\s*([A-Z0-9\-/]{3,30})",
        r"(?:LIVRAISON\s*N[°o]?)\s*[:\-]?\s*([A-Z0-9\-/]{3,30})",
        r"(BL[-/]\d{2,4}[-/]\d{2,8})",
    ],
    "ref_facture": [
        r"(?:N[°o]?\s*(?:FAC(?:TURE)?|FACTURE|FT))\s*[:\-]?\s*([A-Z0-9\-/]{3,30})",
        r"(?:FACTURE\s*N[°o]?)\s*[:\-]?\s*([A-Z0-9\-/]{3,30})",
        r"(FT[-/]?\d{2}[-/]\d{4,8})",
        r"(FAC[-/]\d{2,4}[-/]\d{2,8})",
    ],
    "ref_bc_linked": [
        r"(?:BC|BON\s*DE\s*COMMANDE|REF\s*BC)\s*[:\-]?\s*([A-Z0-9\-/]{3,30})",
        r"(BC[-/]\d{2,4}[-/]\d{2,8})",
    ],
    "date": [
        r"(?:DATE|LE|DU)\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
        r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
    ],
    "total_ht": [
        r"(?:TOTAL\s*H\.?\s*T\.?|MONTANT\s*HT|TOTAL\s*HORS\s*TAXES)\s*[:\-]?\s*([\d\s.,]+)",
    ],
    "total_ttc": [
        r"(?:TOTAL\s*T\.?\s*T\.?\s*C\.?|MONTANT\s*TTC|NET\s*À\s*PAYER)\s*[:\-]?\s*([\d\s.,]+)",
    ],
    "tva_rate": [
        r"(?:TVA|T\.V\.A\.)\s*(?:@|À|A|:)?\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*%",
        r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%\s*(?:TVA|T\.V\.A\.)",
    ],
    "supplier_name": [
        r"(?:FOURNISSEUR|VENDEUR|DE\s*:?)\s*[:\-]?\s*([A-ZÀ-Ÿa-zà-ÿ\s&\.]{3,80})",
    ],
}

# Table column header patterns
_TABLE_HEADER_PATTERNS = {
    "ref_produit": [r"R[ÉE]F[.\s]*(?:PRODUIT|ART|ARTICLE)?", r"CODE\s*(?:ARTICLE|PRODUIT)?", r"R[ÉE]F\.?"],
    "designation": [r"D[ÉE]SIGNATION", r"LIBELL[ÉE]", r"DESCRIPTION", r"ARTICLE"],
    "qty": [r"(?:QT[ÉE]|QUANTIT[ÉE]|QTE|NB)\b", r"QT[ÉE]\.?"],
    "unit": [r"UNIT[ÉE]", r"U\.?M\.?", r"MESURE"],
    "prix_unitaire": [r"PRIX\s*U(?:NIT\.?)?(?:\s*H\.?T\.?)?", r"P\.?\s*U\.?\s*H\.?T\.?", r"P\.?U\.?"],
    "tva_rate": [r"T\.?V\.?A\.?", r"TVA\s*%"],
    "total_ligne": [r"TOTAL\s*H\.?T\.?", r"MONTANT\s*H\.?T\.?", r"TOTAL\s*LIGNE"],
}

# ─────────────────────────────────────────────────────────────────────────────
# Spatial column detection patterns (used with bounding-box extraction)
# Keys must match ColumnDef.name values used in SpatialRow
# ─────────────────────────────────────────────────────────────────────────────
_SPATIAL_COLUMN_PATTERNS = {
    "ref_produit":   [r"R[ÉE]F[.\s]*(?:PRODUIT|ART(?:ICLE)?)?", r"CODE\s*(?:ARTICLE|PRODUIT)?", r"R[ÉE]F\.?", r"ARTICLE"],
    "designation":   [r"D[ÉE]SIGNATION", r"LIBELL[ÉE]", r"DESCRIPTION"],
    "qty":           [r"(?:QT[ÉE]|QUANTIT[ÉE]|QTE|NB)\b", r"QT[ÉE]\.?"],
    "unit":          [r"UNIT[ÉE]", r"U\.?M\.?", r"MESURE"],
    "prix_unitaire": [r"PRIX\s*U(?:NIT\.?)?(?:\s*H\.?T\.?)?", r"P\.?\s*U\.?\s*H\.?T\.?", r"P\.?U\.?", r"PRIX\s*UN"],
    "tva_rate":      [r"T\.?V\.?A\.?", r"TVA\s*%"],
    "total_ligne":   [r"TOTAL\s*H\.?T\.?", r"MONTANT\s*H\.?T\.?", r"TOTAL\s*LIGNE", r"TOTAL\s*HT"],
}


def _spatial_row_to_line_item(row: SpatialRow, line_num: int) -> LineItemSchema | None:
    """
    Convert a SpatialRow (one table row extracted by bounding-box analysis)
    to a LineItemSchema.

    Raw strings are preserved in raw_* fields.
    Numeric parsing uses parse_quantity / parse_money — no rounding, no
    hardcoded corrections.
    Per-field confidence comes from the average OCR word confidence of the
    words assigned to each column.
    """
    # ── Reference ─────────────────────────────────────────────────────────────
    raw_ref = row.raw_ref.strip() or None
    ref_parsed = normalize_reference(raw_ref) if raw_ref else None

    # ── Designation ──────────────────────────────────────────────────────────
    raw_des = row.raw_designation.strip() or None
    des_parsed = normalize_text(raw_des) if raw_des else None

    # ── Quantity ──────────────────────────────────────────────────────────────
    qty_val, qty_raw = parse_quantity(row.raw_qty or "")
    raw_qty_str = qty_raw if qty_raw else None

    # ── Unit price ────────────────────────────────────────────────────────────
    prix_val, prix_raw = parse_money(row.raw_unit_price or "")
    raw_prix_str = prix_raw if prix_raw else None

    # ── TVA rate ──────────────────────────────────────────────────────────────
    tva_val: Decimal | None = None
    if row.raw_tva.strip():
        tva_str = re.sub(r"%", "", row.raw_tva).strip()
        tva_val, _ = parse_money(tva_str)

    # ── Total ─────────────────────────────────────────────────────────────────
    total_val, total_raw = parse_money(row.raw_total or "")
    raw_total_str = total_raw if total_raw else None

    # Skip rows that have nothing useful
    if not any([ref_parsed, des_parsed, qty_val, prix_val]):
        return None

    # ── Line confidence (minimum of available field confidences) ─────────────
    field_confs = [c for c in [
        row.ref_confidence if raw_ref else None,
        row.qty_confidence if qty_val is not None else None,
        row.unit_price_confidence if prix_val is not None else None,
    ] if c is not None]
    line_conf = min(field_confs) if field_confs else 0.5
    has_low = line_conf < 0.70

    return LineItemSchema(
        line_number=line_num,
        ref_produit=ref_parsed,
        ref_produit_normalized=ref_parsed,
        designation=des_parsed,
        qty=qty_val,
        unit=row.raw_unit.strip() or None,
        prix_unitaire=prix_val,
        tva_rate=tva_val,
        total_ligne_ht=total_val,
        raw_reference=raw_ref,
        raw_designation=raw_des,
        raw_qty=raw_qty_str,
        raw_unit_price=raw_prix_str,
        raw_total=raw_total_str,
        line_confidence=line_conf,
        reference_confidence=row.ref_confidence,
        designation_confidence=row.designation_confidence,
        quantity_confidence=row.qty_confidence,
        unit_price_confidence=row.unit_price_confidence,
        total_confidence=row.total_confidence,
        extraction_confidence=line_conf,
        has_low_confidence=has_low,
    )


async def _extract_line_items_spatial(
    raw_ocr_data_per_page: dict,
    pages: list[int],
) -> list[LineItemSchema]:
    """
    Spatial extraction: use word bounding boxes to detect column layout
    and reconstruct line items for each page in the group.

    For every page that has OCR data, run the full spatial pipeline:
      1. Extract word boxes from pytesseract raw_data
      2. Group words into rows by Y proximity
      3. Detect table header row using _SPATIAL_COLUMN_PATTERNS
      4. Compute column X boundaries
      5. For each data row: assign words to columns, extract cell text
    Returns a flat list of LineItemSchema (across all pages).
    """
    items: list[LineItemSchema] = []
    line_num = 0
    for page_num in sorted(pages):
        raw_data = raw_ocr_data_per_page.get(page_num)
        if not raw_data:
            continue
        spatial_rows = extract_spatial_rows(
            raw_data,
            column_patterns=_SPATIAL_COLUMN_PATTERNS,
            y_tolerance=6,
            min_columns=3,
        )
        for s_row in spatial_rows:
            line_num += 1
            item = _spatial_row_to_line_item(s_row, line_num)
            if item:
                items.append(item)
                if item and item.designation:
                    item.designation = await word_dictionary.normalize_text(
                        item.designation, field_name="designation"
                    )
    return items


def _extract_with_patterns(
    text: str,
    patterns: list[str],
    supplier_aliases: dict | None = None,
) -> tuple[str | None, float]:
    """
    Try each regex pattern in order, return (first_match, confidence).

    supplier_aliases is a dict mapping supplier-specific label strings to their
    canonical equivalents (e.g. {"P.U HT": "PRIX_UNITAIRE_HT"]).
    Aliases are substituted into the text before pattern matching so that
    supplier-specific column names are treated identically to canonical names.
    """
    text_upper = text.upper()

    if supplier_aliases:
        for alias, canonical_label in supplier_aliases.items():
            text_upper = text_upper.replace(alias.upper(), canonical_label.upper())

    for pattern in patterns:
        match = re.search(pattern, text_upper, re.MULTILINE)
        if match:
            groups = match.groups()
            if groups:
                raw_value = groups[-1].strip()
                if raw_value:
                    return raw_value, 0.85
    return None, 0.0


_FOOTER_KEYWORDS = frozenset([
    "TOTAL HORS TAXES",
    "NET HORS TAXES",
    "TOTAL TTC",
    "MONTANT T.T.C",
    "NET À PAYER",
    "NET A PAYER",
    "SOUS-TOTAL",
    "MONTANT TTC",
    "ARRETEE LA PRESENTE",
])

_FOOTER_LINE_RE = re.compile(
    r"^\s*(?:TOTAL\s+H\.?\s*T\.?|MONTANT\s+H\.?\s*T\.?)\s*[:\-]?\s*[\d\s,.]+",
    re.IGNORECASE,
)

def _extract_line_items(text: str, supplier_profile: "SupplierProfile | None" = None) -> list[LineItemSchema]:
    """
    Extract line items table from document text.
    Strategy: find table header row, then parse each subsequent row.
    """
    lines = text.splitlines()
    items: list[LineItemSchema] = []
    header_row_idx = -1
    col_positions: dict[str, int] = {}
    for i, line in enumerate(lines):
        line_upper = line.upper()
        found_cols = 0
        for col_name, patterns in _TABLE_HEADER_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, line_upper):
                    match = re.search(pattern, line_upper)
                    if match:
                        col_positions[col_name] = match.start()
                        found_cols += 1
                    break
        if found_cols >= 3:
            header_row_idx = i
            break

    if header_row_idx == -1:
        logger.debug("table_header_not_found", text_length=len(text))
        return items
    line_num = 0
    for line in lines[header_row_idx + 1:]:
        line = line.strip()
        if not line or len(line) < 5:
            continue
        if not re.search(r"\d", line):
            continue
        line_upper = line.upper()
        if any(kw in line_upper for kw in _FOOTER_KEYWORDS):
            break
        if _FOOTER_LINE_RE.match(line):
            break
        parts = re.split(r"\s{2,}|\t", line) 
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) < 2:
            continue
        line_num += 1
        item = _parse_line_parts(parts, col_positions, line_num)
        if item:
            items.append(item)

    return items


def _parse_line_parts(parts: list[str], col_positions: dict, line_num: int) -> LineItemSchema | None:
    """
    Parse a whitespace-split OCR line into a LineItemSchema.

    Fallback path used when bounding-box data is unavailable (NATIVE pages or
    when raw_ocr_data_per_page is empty).  When bounding boxes are available,
    _extract_line_items_spatial is used instead and produces better results.

    Assignment strategy (left-to-right in OCR order):
      - Text tokens → first = ref_produit, rest = designation
      - "N%" token   → tva_rate (only if % is explicit in the raw string)
      - Numeric tokens in order → qty, prix_unitaire, total_ligne_ht
        (no magnitude-based heuristic — order in the OCR text determines role)

    Raw strings are preserved for display; parse_quantity / parse_money are
    used for numeric parsing so no rounding occurs.
    """
    if not parts:
        return None

    raw_ref: str | None = None
    raw_des: str | None = None
    raw_qty_str: str | None = None
    raw_prix_str: str | None = None
    raw_total_str: str | None = None

    qty: Decimal | None = None
    prix_unitaire: Decimal | None = None
    tva_rate: Decimal | None = None
    total_ligne: Decimal | None = None
    text_parts: list[str] = []

    for part in parts:
        cleaned = re.sub(r"[€%\s]", "", part.replace(",", "."))
        try:
            float(cleaned)
            is_numeric = True
        except ValueError:
            is_numeric = False

        if not is_numeric:
            text_parts.append(part)
            continue
        if tva_rate is None and "%" in part:
            tva_str = re.sub(r"%", "", part).strip()
            tva_val, _ = parse_money(tva_str)
            if tva_val is not None and 0 < float(tva_val) <= 30:
                tva_rate = tva_val
                continue
        if qty is None:
            val, raw = parse_quantity(part)
            if val is not None:
                qty = val
                raw_qty_str = raw
        elif prix_unitaire is None:
            val, raw = parse_money(part)
            if val is not None:
                prix_unitaire = val
                raw_prix_str = raw
        elif total_ligne is None:
            val, raw = parse_money(part)
            if val is not None:
                total_ligne = val
                raw_total_str = raw

    if text_parts:
        raw_ref = text_parts[0]
        raw_des = " ".join(text_parts[1:]) if len(text_parts) > 1 else None

    if not any([raw_ref, qty, prix_unitaire]):
        return None

    ref_parsed = normalize_reference(raw_ref) if raw_ref else None
    confidence = 0.75 if (ref_parsed and qty) else 0.5
    has_low = confidence < 0.70

    return LineItemSchema(
        line_number=line_num,
        ref_produit=ref_parsed,
        ref_produit_normalized=ref_parsed,
        designation=normalize_text(raw_des) if raw_des else None,
        qty=qty,
        prix_unitaire=prix_unitaire,
        tva_rate=tva_rate,
        total_ligne_ht=total_ligne,
        raw_reference=raw_ref,
        raw_designation=raw_des,
        raw_qty=raw_qty_str,
        raw_unit_price=raw_prix_str,
        raw_total=raw_total_str,
        extraction_confidence=confidence,
        has_low_confidence=has_low,
    )


async def extract_document_template(
    group: DocumentGroup,
    supplier_profile: "SupplierProfile | None" = None,
) -> BonDeCommandeSchema | BonDeLivraison | FactureSchema | None:
    """
    Tier 1 extraction: template-based using regex patterns + supplier profile aliases.
    Returns the appropriate schema or None if extraction confidence is too low.
    """
    text = group.combined_text
    doc_type = group.doc_type
    field_confidence: dict[str, float] = {}
    if supplier_profile and supplier_profile.field_aliases:
        aliases = supplier_profile.field_aliases.get(doc_type.value, {})
        for alias, canonical in aliases.items():
            text = re.sub(re.escape(alias.upper()), canonical.upper(), text.upper(), flags=re.IGNORECASE)
    use_spatial = bool(group.raw_ocr_data_per_page)

    if doc_type == DocumentType.BC:
        ref_raw, ref_conf = _extract_with_patterns(text, _HEADER_PATTERNS["ref_bc"])
        date_raw, date_conf = _extract_with_patterns(text, _HEADER_PATTERNS["date"])
        supplier_raw, _ = _extract_with_patterns(text, _HEADER_PATTERNS["supplier_name"])
        if not ref_raw:
            return None

        lines: list[LineItemSchema] = []
        if use_spatial:
            try:
                lines = await _extract_line_items_spatial(group.raw_ocr_data_per_page, group.pages)
            except Exception as spatial_exc:
                logger.warning(
                    "spatial_extraction_failed doc_type=BC pages=%s error=%s",
                    group.pages,
                    str(spatial_exc),
                )
        if not lines:
            lines = _extract_line_items(text, supplier_profile)
        # Remove annotation-only or non-product lines discovered by the LLM/template
        lines = [ln for ln in lines if _is_valid_product_line(ln)]
        date_parsed = normalize_date(date_raw, supplier_profile.date_format if supplier_profile else None)
        field_confidence["ref_bc"] = ref_conf
        field_confidence["document_date"] = date_conf
        has_low_conf = any(v < 0.70 for v in field_confidence.values())
        return BonDeCommandeSchema(
            ref_bc=normalize_reference(ref_raw),
            document_date=date_parsed,
            supplier_name=normalize_text(supplier_raw) if supplier_raw else None,
            lines=lines,
            extraction_source_tier=ExtractionTier.TEMPLATE,
            extraction_confidence=min(field_confidence.values()) if field_confidence else 0.7,
            field_confidence_map=field_confidence,
            has_low_confidence_fields=has_low_conf,
        )

    elif doc_type == DocumentType.BL:
        ref_raw, ref_conf = _extract_with_patterns(text, _HEADER_PATTERNS["ref_bl"])
        ref_bc_raw, ref_bc_conf = _extract_with_patterns(text, _HEADER_PATTERNS["ref_bc_linked"])
        date_raw, date_conf = _extract_with_patterns(text, _HEADER_PATTERNS["date"])

        if not ref_raw:
            return None

        lines: list[LineItemSchema] = []
        if use_spatial:
            try:
                lines = await _extract_line_items_spatial(group.raw_ocr_data_per_page, group.pages)
            except Exception as spatial_exc:
                logger.warning(
                    "spatial_extraction_failed doc_type=BL pages=%s error=%s",
                    group.pages,
                    str(spatial_exc),
                )
        if not lines:
            lines = _extract_line_items(text, supplier_profile)
        # Remove annotation-only or non-product lines discovered by the LLM/template
        lines = [ln for ln in lines if _is_valid_product_line(ln)]
        date_parsed = normalize_date(date_raw, supplier_profile.date_format if supplier_profile else None)
        field_confidence = {"ref_bl": ref_conf, "document_date": date_conf}
        return BonDeLivraison(
            ref_bl=normalize_reference(ref_raw),
            ref_bc_linked=normalize_reference(ref_bc_raw) if ref_bc_raw else None,
            document_date=date_parsed,
            lines=lines,
            extraction_source_tier=ExtractionTier.TEMPLATE,
            extraction_confidence=min(field_confidence.values()),
            field_confidence_map=field_confidence,
            has_low_confidence_fields=any(v < 0.70 for v in field_confidence.values()),
        )

    elif doc_type == DocumentType.FACTURE:
        ref_raw, ref_conf = _extract_with_patterns(text, _HEADER_PATTERNS["ref_facture"])
        ref_bc_raw, _ = _extract_with_patterns(text, _HEADER_PATTERNS["ref_bc_linked"])
        date_raw, date_conf = _extract_with_patterns(text, _HEADER_PATTERNS["date"])
        total_ht_raw, ht_conf = _extract_with_patterns(text, _HEADER_PATTERNS["total_ht"])
        total_ttc_raw, ttc_conf = _extract_with_patterns(text, _HEADER_PATTERNS["total_ttc"])
        tva_raw, tva_conf = _extract_with_patterns(text, _HEADER_PATTERNS["tva_rate"])

        if not ref_raw:
            return None

        lines: list[LineItemSchema] = []
        if use_spatial:
            try:
                lines = await _extract_line_items_spatial(group.raw_ocr_data_per_page, group.pages)
            except Exception as spatial_exc:
                logger.warning(
                    "spatial_extraction_failed doc_type=FACTURE pages=%s error=%s",
                    group.pages,
                    str(spatial_exc),
                )
        if not lines:
            lines = _extract_line_items(text, supplier_profile)
        # Remove annotation-only or non-product lines discovered by the LLM/template
        lines = [ln for ln in lines if _is_valid_product_line(ln)]
        date_parsed = normalize_date(date_raw, supplier_profile.date_format if supplier_profile else None)
        field_confidence = {
            "ref_facture": ref_conf,
            "document_date": date_conf,
            "total_ht": ht_conf,
            "total_ttc": ttc_conf,
        }

        return FactureSchema(
            ref_facture=normalize_reference(ref_raw),
            ref_bc_linked=normalize_reference(ref_bc_raw) if ref_bc_raw else None,
            document_date=date_parsed,
            total_ht=normalize_number(total_ht_raw) if total_ht_raw else None,
            total_ttc=normalize_number(total_ttc_raw) if total_ttc_raw else None,
            tva_rate=normalize_number(tva_raw) if tva_raw else None,
            lines=lines,
            extraction_source_tier=ExtractionTier.TEMPLATE,
            extraction_confidence=min(field_confidence.values()),
            field_confidence_map=field_confidence,
            has_low_confidence_fields=any(v < 0.70 for v in field_confidence.values()),
        )

    return None


# ─────────────────────────────────────────────────────────────────────────────
# TIER 3: LLM Fallback Extraction
# ─────────────────────────────────────────────────────────────────────────────

_LINE_ITEM_SCHEMA = {
    "line_number": "integer",
    "ref_produit": "string or null (reconstructed product reference)",
    "ref_confidence": "number 0.0-1.0 (1.0=exact read, <1.0=reconstructed)",
    "designation": "string (cleaned, OCR-reconstructed product name)",
    "designation_confidence": "number 0.0-1.0",
    "qty": "number or null",
    "unit": "string or null",
    "prix_unitaire": "number or null",
    "remise_pct": "number or null (discount percentage if present)",
    "tva_rate": "number or null (percentage, e.g. 19)",
    "total_ligne_ht": "number or null",
    "ocr_issues_detected": "boolean (true if OCR artifacts were found and corrected)",
    "reconstruction_notes": "string or null (explain any corrections made)",
}

_LLM_SCHEMA_BY_TYPE = {
    DocumentType.BC: {
        "ref_bc": "string (document reference number)",
        "document_date": "string (DD/MM/YYYY)",
        "supplier_name": "string",
        "line_count_in_document": "integer (exact row count you counted in the table)",
        "lines": [_LINE_ITEM_SCHEMA],
        "extraction_warnings": ["string"],
    },
    DocumentType.BL: {
        "ref_bl": "string",
        "ref_bc_linked": "string or null",
        "document_date": "string (DD/MM/YYYY)",
        "supplier_name": "string",
        "line_count_in_document": "integer (exact row count you counted in the table)",
        "lines": [_LINE_ITEM_SCHEMA],
        "extraction_warnings": ["string"],
    },
    DocumentType.FACTURE: {
        "ref_facture": "string",
        "ref_bc_linked": "string or null",
        "document_date": "string (DD/MM/YYYY)",
        "supplier_name": "string",
        "total_ht": "number",
        "total_tva": "number",
        "total_ttc": "number",
        "tva_rate": "number (percentage)",
        "line_count_in_document": "integer (exact row count you counted in the table)",
        "lines": [_LINE_ITEM_SCHEMA],
        "extraction_warnings": ["string"],
    },
}


def _extract_json_from_text(text: str) -> dict | None:
    """
    Extract the first valid top-level JSON object from LLM output.

    Uses a character-level brace-stack scan rather than a greedy regex so
    that nested objects inside the response (e.g. a thinking preamble followed
    by the actual JSON) are handled correctly.

    Falls back to stripping markdown fences and re-trying a direct parse.
    """
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    stripped = re.sub(r"^```(?:json)?\s*\n?", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\n?```\s*$", "", stripped, flags=re.IGNORECASE)
    try:
        return json.loads(stripped.strip())
    except json.JSONDecodeError:
        pass

    depth = 0
    start: int | None = None
    in_string = False
    escape_next = False

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = None

    logger.warning("_extract_json_from_text: no valid JSON object found in LLM output")
    return None


def _build_system_prompt(schema: dict, supplier_profile=None) -> str:
    """
    Build the LLM extraction system prompt dynamically.

    Supplier-specific hints (ref patterns, column layout, OCR corrections)
    are injected from the supplier profile when available. No supplier name,
    product reference, or domain keyword is hardcoded here.
    """
    # ── Supplier-specific sections (empty strings when no profile) ─────────────
    supplier_ref_section = ""
    supplier_column_section = ""
    supplier_ocr_section = ""

    if supplier_profile is not None:
        ref_patterns: list[str] = getattr(supplier_profile, "ref_patterns", []) or []
        if ref_patterns:
            examples = "\n".join(f"  {p}" for p in ref_patterns[:8])
            supplier_ref_section = (
                "\nKnown reference patterns for this supplier (regex):\n"
                + examples
                + "\n- Apply these patterns first before falling back to generic detection."
            )

        column_layout: dict = getattr(supplier_profile, "column_layout", {}) or {}
        if column_layout.get("columns"):
            col_names = [c.get("name", "") for c in column_layout["columns"]]
            supplier_column_section = (
                "\nDetected column order for this supplier: "
                + " | ".join(col_names)
                + "\nUse this order when column headers are ambiguous."
            )

        ocr_corrections: dict = getattr(supplier_profile, "ocr_corrections", {}) or {}
        if ocr_corrections:
            pairs = ", ".join(f'"{k}" → "{v}"' for k, v in list(ocr_corrections.items())[:10])
            supplier_ocr_section = (
                "\nSupplier-specific OCR corrections (apply before generic rules): " + pairs
            )

    return f"""You are an expert OCR post-processor for B2B business documents (invoices, purchase orders,
delivery notes). Documents may be in French, Arabic, or mixed language from any industrial supplier.
OCR output is UNRELIABLE — apply corrections using BOTH the OCR text AND the page image(s).
The image is the ground truth; the OCR text is a hint only.

════════════════════════════════════════════════════════════
CRITICAL RULES (apply before anything else)
════════════════════════════════════════════════════════════
1. NEVER invent a line item that does not exist in the document.
2. PRESERVE product codes and article references EXACTLY as printed — never alter them.
3. NEVER replace a product reference with a designation, or vice versa.
4. NEVER correct monetary amounts, dates, tax rates, discounts, prices, or quantities by intuition.
5. If a value is illegible, return null and lower the confidence score.
6. Use the supplier profile as a HINT, not as ground truth.
7. ALL supplier-specific vocabulary must come from the injected supplier profile below — NOT from
   any pre-trained knowledge about specific companies.
8. Always return both raw_value and corrected_value when a correction is applied.
9. If a token looks like a product code (alphanumeric, mixed letters+digits), keep it exactly.
10. Do not apply knowledge specific to any particular supplier unless it is injected below
    via the supplier profile section.

════════════════════════════════════════════════════════════
STEP 1 — COUNT ROWS FIRST
════════════════════════════════════════════════════════════
Before extracting anything, count every data row in the line-item table (exclude header row,
subtotal rows, and footer rows). Record this count in "line_count_in_document". Then extract
EXACTLY that many line items. If len(lines) < line_count_in_document, go back and find the missing rows.

MULTI-PAGE AND DUPLICATE-ROW RULES (critical):
a) A document may span multiple pages. The page containing TOTALS/NET/REMISE is a summary page —
   it does NOT replace or cancel the page(s) containing the article rows. Extract items from ALL pages.
b) An article row whose description wraps onto the next visual line is ONE line item, not two.
   Lines starting with SPEC:, REF, or a BL/delivery reference (e.g. "BL2460/2025") that appear
   immediately below an article row are CONTINUATION of that article's description — they are NOT
   separate line items.
c) If the same article_code appears more than once in the table with DIFFERENT quantities, prices,
   or delivery dates, return EACH occurrence as a SEPARATE line item. NEVER merge or deduplicate
   rows that share an article_code.
d) Do NOT delete a line item simply because its description contains a BL reference or a spec code.
e) The totals page (containing TOTAL HORS TAXES, NET A PAYER, REMISE, etc.) must not contribute
   any line items — only the article table page(s) do.

════════════════════════════════════════════════════════════
STEP 2 — DOCUMENT TYPE DETECTION
════════════════════════════════════════════════════════════
Identify document type from keywords:
- FACTURE (invoice):             facture, fac, fact, N° fac
- BON_COMMANDE (purchase order): bon de commande, commande, N° BC, B.C
- BON_LIVRAISON (delivery note):  bon de livraison, livraison, N° BL, B.L, réception
Use "document_type" field in the output. If ambiguous, pick the most likely type.

════════════════════════════════════════════════════════════
STEP 3 — OCR ARTIFACT CLEANING (apply to every cell)
════════════════════════════════════════════════════════════
a) LETTER/DIGIT SUBSTITUTIONS — apply ONLY for designation/label words, NOT for codes or numbers:
   0↔O, 1↔I↔L, 8↔B, 5↔S, 6↔G, 2↔Z, 4↔A, rn→m, cl→d, vv→w

b) MERGED WORDS — split concatenated words when two known terms are joined without space.

c) COLUMN BLEED — remove isolated single characters between columns (OCR border artifacts).
   Remove trailing "—", "...", and isolated digits/letters at end of designation strings.

d) EMBEDDED DELIVERY CODES — remove BL/delivery references inside designations
   (e.g. "BL/XX/12345", lot codes like "25/01983"). These are NOT product descriptions.

e) FRACTIONS — preserve as-is: "10 1/2", "1/4 G", "1/2 G"

f) DIMENSIONS — preserve technical dimension codes exactly: "595X395X330", "1200*1000", "115X22.23"
{supplier_ocr_section}

════════════════════════════════════════════════════════════
STEP 4 — REFERENCE EXTRACTION
════════════════════════════════════════════════════════════
A product reference code is typically: alphanumeric, 4-15 chars, may contain hyphens/dots/slashes,
appears in a dedicated column (Référence/Article/Code/Réf), often starts with letters then digits.
{supplier_ref_section}

General rules:
- PRESERVE codes exactly — do not alter mixed alphanumeric tokens.
- If reconstruction is uncertain → set ref_confidence ≤ 0.5 and explain in reconstruction_notes.
- NEVER copy pure OCR garbage — use image + designation context to reconstruct.
- Remove accented characters from refs (é→e, è→e, à→a) only when confident.
- A lot/date code (e.g. "25/01983") in the FIRST column of a FACTURE is NOT a product ref.

════════════════════════════════════════════════════════════
STEP 5 — COLUMN STRUCTURE
════════════════════════════════════════════════════════════
Detect columns by their headers. Common headers and semantic meaning:
- Référence / Article / Code / Réf / Art → REFERENCE (ref_produit)
- Désignation / Description / Libellé     → DESIGNATION
- Quantité / Qté / Qt / Qte / NB         → QUANTITY (qty)
- U.M / UM / Unité / Mesure              → UNIT (unit)
- Prix Unit / P.U.HT / Prix HT / Prix UN → UNIT_PRICE (prix_unitaire)
- Montant HT / Total HT / Tot HT         → TOTAL_HT (total_ligne_ht)
- TVA / %TVA / Taux TVA                  → TAX_RATE (tva_rate)
- Remise / % Rem / Rabais                → DISCOUNT (remise_pct)
{supplier_column_section}

════════════════════════════════════════════════════════════
STEP 6 — NUMBERS (CRITICAL: READ FROM IMAGE, NOT OCR TEXT)
════════════════════════════════════════════════════════════
⚠️  PRICES ARE THE MOST CRITICAL FIELD — A 100× ERROR COSTS REAL MONEY.

Tunisian Dinar (TND) uses 3 decimal places (millimes):
  "122.341" = 122 dinars 341 millimes → return EXACTLY 122.341 (NOT 122 or 1.22 or 1223.41)
  "415.959" = 415 dinars 959 millimes → return EXACTLY 415.959
  "5.568"   = 5 dinars 568 millimes   → return EXACTLY 5.568
  "4.339"   = 4 dinars 339 millimes   → return EXACTLY 4.339
  "6.207"   = 6 dinars 207 millimes   → return EXACTLY 6.207

OCR often misreads decimal separators:
  OCR says "122 341" → IMAGE shows "122.341" → return 122.341
  OCR says "1,23"    → IMAGE shows "122.341" → return 122.341 (100× error!)
  OCR says "4,39"    → IMAGE shows "4.339"   → return 4.339
  OCR says "6,31"    → IMAGE shows "6.207"   → return 6.207

🔴 MANDATORY RULE: For EVERY price field (prix_unitaire, total_ligne_ht):
   1. Look at the IMAGE first (not OCR text)
   2. Count the digits carefully: "122.341" has 6 digits (3 before, 3 after decimal)
   3. If OCR text disagrees with image, TRUST THE IMAGE
   4. If image is blurry, set prix_confidence ≤ 0.5 and return null
   5. NEVER round: 122.341 stays 122.341, NOT 122.34 or 122

OCR spaces in numbers: "5 568" → 5.568 | "122 341" → 122.341
Both . and , are valid decimal separators in TND amounts.
NEVER multiply by 1000. NEVER strip the decimal.
Quantities: "~ 4.0" or "- 4.0" → qty=4.0 | empty/"—" → qty=null
Integers: 10.0→10, 4.0→4 (return as integer when no fractional part)
prix_unitaire is the SMALL per-unit number; total_ligne_ht is the LARGE line total.

✓ SELF-CHECK: If prix_unitaire < 1.0 but total_ligne_ht > 100, you made a 100× error. Go back.

════════════════════════════════════════════════════════════
STEP 7 — SELF-VALIDATION before returning
════════════════════════════════════════════════════════════
✓ len(lines) == line_count_in_document (if not, go back and find missing rows)
✓ No designation ends with "—", "...", or an isolated digit/letter
✓ No designation contains embedded delivery codes or client names
✓ No ref_produit contains accented characters
✓ No ref_produit is pure OCR garbage (flag with ref_confidence ≤ 0.5 if uncertain)
✓ qty × prix_unitaire ≈ total_ligne_ht (±20% after remise). If factor-of-10 error, re-read.
✓ All reconstructed refs have ref_confidence < 1.0
✓ No product code has been "translated" or "cleaned" — codes are preserved verbatim.
✓ Report any tokens that could not be corrected in "unknown_tokens" list

════════════════════════════════════════════════════════════
OUTPUT
════════════════════════════════════════════════════════════
Return ONLY valid JSON. No markdown, no explanation, no trailing text.
Dates: return as string in document format (e.g. "10/09/2025").
Document reference: extract exactly as printed after "Facture N°", "N° BC", etc.
"unknown_tokens": list any OCR tokens (designation words only) that could not be corrected.
  Do NOT include product codes, amounts, or dates in unknown_tokens.

Required JSON schema:
{json.dumps(schema, indent=2)}"""


def _post_process_llm_result(raw: dict) -> dict:
    """Clean artifacts from LLM extraction output and flag low-confidence refs."""
    _trailing = re.compile(r'[\s—\-\.…]+$')
    _accented = re.compile(r'[àáâãäçèéêëìíîïñòóôõöùúûüÀÁÂÃÄÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜ]')
    _bad_ref_chars = re.compile(r'[^A-Za-z0-9\-]')

    for line in raw.get("lines", []):
        des = (line.get("designation") or "").strip()
        des = _trailing.sub("", des).strip()
        line["designation"] = des
        ref = (line.get("ref_produit") or "").strip()
        if ref:
            if _accented.search(ref) or _bad_ref_chars.search(ref):
                line["ref_confidence"] = min(float(line.get("ref_confidence") or 1.0), 0.4)
                line["ocr_issues_detected"] = True
                existing_note = line.get("reconstruction_notes") or ""
                line["reconstruction_notes"] = (
                    (existing_note + " | " if existing_note else "")
                    + f"Ref '{ref}' contains invalid characters — needs manual review"
                )
        for key in ("ref_confidence", "designation_confidence"):
            val = line.get(key)
            if val is not None:
                try:
                    line[key] = max(0.0, min(1.0, float(val)))
                except (TypeError, ValueError):
                    line[key] = 0.5

    return raw
_PRINTED_PAGE_RE = re.compile(
    r"\bPAGE\s*[:\.]?\s*(\d+)\b",
    re.IGNORECASE,
)
def _extract_printed_page_number(text: str) -> int | None:
    """
    Extract the printed page number from the first 600 chars of a page's OCR text.
    Handles patterns like "PAGE : 1", "PAGE 2", "PAGE: 1 *Suite*".
    Returns None if no printed page number is found.
    """
    m = _PRINTED_PAGE_RE.search(text[:600])
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


_GENERIC_REF_PATTERNS = [
    r'\b[A-Z]\d{6,}\b',          # P199680136, M400010432
    r'\b[A-Z]{2,4}\d{4,}\b',     
]


def _count_visible_article_refs(text: str, supplier_profile=None) -> int:
    """
    Count distinct article reference codes visible in OCR text.

    Uses supplier profile ref_patterns when available, otherwise falls back to
    generic alphanumeric code patterns. Counts unique refs so that multi-page
    duplicates don't inflate the estimate.
    """
    patterns: list[str] = []
    if supplier_profile is not None:
        patterns = list(getattr(supplier_profile, "ref_patterns", []) or [])
    if not patterns:
        patterns = _GENERIC_REF_PATTERNS

    refs: set[str] = set()
    for pat in patterns:
        try:
            refs.update(re.findall(pat, text))
        except re.error:
            pass
    return len(refs)


def _reorder_group_by_printed_pages(
    group: DocumentGroup,
) -> tuple[str, list[int]]:
    """
    Re-order the pages of a multi-page document group by their printed page number
    instead of their PDF page number.

    Returns:
      - reordered_combined_text: OCR text in logical page order
      - ordered_pdf_page_numbers: PDF page numbers in the logical order

    Falls back to the original order when:
      - fewer than 2 pages, or
      - page_texts is not populated, or
      - printed page numbers could not be detected for every page.
    """
    page_texts: dict[int, str] = getattr(group, "page_texts", {})
    pdf_pages = sorted(group.page_images_b64.keys()) if group.page_images_b64 else list(group.pages)

    if not page_texts or len(page_texts) <= 1:
        return group.combined_text, pdf_pages

    detected: list[tuple[int, int, str]] = [] 
    for pdf_pn, text in page_texts.items():
        printed = _extract_printed_page_number(text)
        if printed is not None:
            detected.append((printed, pdf_pn, text))
    if len(detected) != len(page_texts):
        return group.combined_text, pdf_pages
    detected.sort(key=lambda x: x[0])
    reordered_text = "\n".join(text for _, _, text in detected)
    ordered_pdf_pages = [pdf_pn for _, pdf_pn, _ in detected]

    original_order = [pdf_pn for _, pdf_pn, _ in sorted(detected, key=lambda x: x[1])]
    if ordered_pdf_pages != original_order:
        logger.info(
            "llm_pages_reordered_by_printed_number doc_type=%s pdf_order=%s logical_order=%s",
            group.doc_type,
            original_order,
            ordered_pdf_pages,
        )

    return reordered_text, ordered_pdf_pages


async def extract_document_llm(
    group: DocumentGroup,
    validation_error: str | None = None,
    _json_retry: bool = False,
    _line_count_retry: bool = False,
    _ref_count_retry: bool = False,
    supplier_profile=None,
) -> dict | None:
    """
    Tier 3 LLM extraction fallback.
    Sends page image(s) + OCR text to GPT-4o vision with a dynamic prompt.
    Retries on JSON parse error, schema error, and line-count mismatch.
    Returns raw dict for caller to map to Pydantic schema.
    """
    schema = _LLM_SCHEMA_BY_TYPE.get(group.doc_type)
    if not schema:
        return None

    system_prompt = _build_system_prompt(schema, supplier_profile=supplier_profile)

    error_note = ""
    if validation_error:
        error_note = f"\n\nNOTE: Your previous response failed: {validation_error}\nFix and return ONLY valid JSON."
    ocr_text_ordered, ordered_pdf_pages = _reorder_group_by_printed_pages(group)

    text_limit = 6000
    ocr_intro = (
        f"Document type: {group.doc_type.value}\n\n"
        f"OCR text (may contain errors — use the page image(s) above to correct them):\n"
        f"---\n{ocr_text_ordered[:text_limit]}\n---{error_note}"
    )
    has_images = bool(group.page_images_b64)
    if has_images:
        user_content: list | str = []
        for pn in ordered_pdf_pages:
            if pn in group.page_images_b64:
                image_detail = "high" if len(ordered_pdf_pages) == 1 else "auto"
        user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{group.page_images_b64[pn]}",
                        "detail": image_detail,
                    },
                })
        user_content.append({"type": "text", "text": ocr_intro})
    else:
        # Fallback: text-only (native PDF pages have no image)
        user_content = (
            f"Document type: {group.doc_type.value}\n\n"
            f"Document text (OCR):\n---\n{group.combined_text[:text_limit]}\n---{error_note}"
        )

    # FACTURE akther waa7da acompelx a3tiha akthr token budget.
    max_tokens = settings.llm_max_tokens
    if group.doc_type == DocumentType.FACTURE:
        max_tokens = max(max_tokens, 4000)
    elif group.doc_type == DocumentType.BC:
        max_tokens = max(max_tokens, 4500)

    payload = {
        "model": settings.llm_model,
        "max_tokens": max_tokens,
        "temperature": settings.llm_temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "content-type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()

        data = response.json()
        raw_text = data["choices"][0]["message"]["content"].strip()
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
        raw_text = re.sub(r"\s*```$", "", raw_text, flags=re.MULTILINE)

        result = _extract_json_from_text(raw_text)
        if result is None:
            if not _json_retry:
                logger.warning(
                    "llm_extraction_json_invalid_retrying",
                    doc_type=group.doc_type,
                    preview=raw_text[:200],
                )
                return await extract_document_llm(
                    group,
                    validation_error=(
                        "Your previous response was not valid JSON. "
                        "Return ONLY a raw JSON object — no markdown, no explanation, "
                        "no trailing text. Ensure every string is quoted and every "
                        "object/array has correct commas between elements."
                    ),
                    _json_retry=True,
                    _ref_count_retry=_ref_count_retry,
                    supplier_profile=supplier_profile,
                )
            logger.error("llm_extraction_parse_error", doc_type=group.doc_type, preview=raw_text[:200])
            return None
        result = _post_process_llm_result(result)
        if not _line_count_retry:
            declared = result.get("line_count_in_document")
            actual = len(result.get("lines", []))
            if declared and isinstance(declared, int) and actual < declared:
                logger.warning(
                    "llm_extraction_line_count_mismatch",
                    doc_type=group.doc_type,
                    declared=declared,
                    actual=actual,
                )
                return await extract_document_llm(
                    group,
                    validation_error=(
                        f"You declared {declared} rows in the table but only returned {actual} line items. "
                        f"You are missing {declared - actual} row(s). "
                        "Go back, count the rows again carefully, and return ALL of them."
                    ),
                    _line_count_retry=True,
                    _ref_count_retry=_ref_count_retry,
                    supplier_profile=supplier_profile,
                )
        if not _ref_count_retry:
            visible_refs = _count_visible_article_refs(ocr_text_ordered, supplier_profile)
            actual = len(result.get("lines", []))
            if visible_refs > actual:
                logger.warning(
                    "llm_extraction_ref_count_mismatch doc_type=%s visible_refs=%d extracted=%d",
                    group.doc_type, visible_refs, actual,
                )
                return await extract_document_llm(
                    group,
                    validation_error=(
                        f"I can count {visible_refs} distinct article reference codes in the document "
                        f"but you only returned {actual} line items. "
                        f"You are missing at least {visible_refs - actual} item(s). "
                        "Rules: (1) do NOT merge rows with the same article_code if their quantities differ; "
                        "(2) continuation lines (SPEC:, REF, BL...) belong to the previous item's description; "
                        "(3) the totals page does not replace the items page. "
                        "Return ALL line items."
                    ),
                    _line_count_retry=_line_count_retry,
                    _ref_count_retry=True,
                    supplier_profile=supplier_profile,
                )

        logger.info(
            "llm_extraction_success",
            doc_type=group.doc_type,
            lines=len(result.get("lines", [])),
            has_images=has_images,
        )
        return result

    except (KeyError, AttributeError) as e:
        logger.error("llm_extraction_response_error doc_type=%s error=%s", group.doc_type, str(e))
        return None
    except httpx.TimeoutException as e:
        logger.error("llm_extraction_timeout doc_type=%s timeout=120s error=%s", group.doc_type, str(e))
        return None
    except httpx.HTTPStatusError as e:
        logger.error("llm_extraction_http_status_error doc_type=%s status=%s error=%s", 
                     group.doc_type, e.response.status_code, str(e))
        return None
    except httpx.HTTPError as e:
        logger.error("llm_extraction_http_error doc_type=%s error=%s", group.doc_type, str(e))
        if not _json_retry:
            import asyncio as _asyncio
            logger.warning("llm_extraction_http_error_retrying doc_type=%s", group.doc_type)
            await _asyncio.sleep(4)
            return await extract_document_llm(
                group,
                validation_error=validation_error,
                _json_retry=True,
                _line_count_retry=_line_count_retry,
                _ref_count_retry=_ref_count_retry,
                supplier_profile=supplier_profile,
            )
        return None


def _scale_correction(qty, prix, total) -> tuple:
    """
    If qty × prix is off from total by a factor close to 10, 100, or 1000,
    scale the price down to match. Returns (corrected_qty, corrected_prix, total).
    This fixes the common OCR issue where TND millimes are read as full dinars.
    """
    if qty is None or prix is None or total is None:
        return qty, prix, total
    try:
        q = float(qty)
        p = float(prix)
        t = float(total)
        if q <= 0 or t <= 0:
            return qty, prix, total
        computed = q * p
        if computed == 0:
            return qty, prix, total
        ratio = computed / t
        for factor in (1000, 100, 10):
            if abs(ratio - factor) / factor < 0.20:
                corrected = Decimal(str(p)) / factor
                return qty, corrected, total
    except Exception:
        pass
    return qty, prix, total


def _is_valid_product_line(line: LineItemSchema) -> bool:
    """
    Return False for lines that are clearly not product entries.

    A valid product line must have at least one of: ref_produit, prix_unitaire,
    or a positive qty.  Lines with only a plain-text designation (person names,
    BL delivery annotations like "// MAG HASSAN AHMED BH", "** MAG MED ALI")
    are excluded.

    This is intentionally permissive: it only rejects lines where ALL numeric
    fields are absent AND the designation contains no digits or product-code
    tokens, so legitimate lines with partial data are preserved.
    """
    has_ref   = bool(line.ref_produit)
    has_price = line.prix_unitaire is not None and line.prix_unitaire > 0
    has_qty   = line.qty is not None and line.qty > 0

    if not (has_ref or has_price or has_qty):
        return False

    # Designation-only line: if every word is purely alphabetic (no digits,
    # no codes), it is an annotation or person name, not a product.
    des = (line.designation or "").strip()
    if not has_ref and not has_price and des:
        words = [w for w in des.split() if len(w) > 1]
        if words and all(re.match(r"^[A-ZÀ-Ÿa-zà-ÿ\-]+$", w) for w in words):
            return False

    return True

def _safe_normalize_ref(value) -> str | None:
    """
    Normalize a reference string from LLM output.
    Returns None (not empty string) when the value is absent, null, or blank.
    The matcher distinguishes between None (no ref present in document) and
    an empty string (ref field present but blank — different condition).
    """
    if not value:
        return None
    normalized = normalize_reference(str(value))
    return normalized if normalized else None


async def map_llm_result_to_schema(
    raw: dict,
    doc_type: DocumentType,
) -> BonDeCommandeSchema | BonDeLivraison | FactureSchema | None:
    """Map LLM raw dict output to the appropriate Pydantic schema."""
    try:
        lines_raw = raw.get("lines", [])
        lines = []
        for i, ln in enumerate(lines_raw):
            raw_qty_str = str(ln["qty"]) if ln.get("qty") is not None else ""
            raw_prix_str = str(ln["prix_unitaire"]) if ln.get("prix_unitaire") is not None else ""
            raw_total_str = str(ln["total_ligne_ht"]) if ln.get("total_ligne_ht") is not None else ""

            qty_val, qty_raw = parse_quantity(raw_qty_str)
            prix_val, prix_raw = parse_money(raw_prix_str)
            total_val, total_raw = parse_money(raw_total_str)
            original_prix = prix_val
            qty_val, prix_val, total_val = _scale_correction(qty_val, original_prix, total_val)
            field_conf: dict = {}
            if prix_val != original_prix:
                field_conf["prix_unitaire"] = 0.5
            raw_ref = ln.get("ref_produit", "")
            raw_des = ln.get("designation", "")
            ref_conf = ln.get("ref_confidence")
            des_conf = ln.get("designation_confidence")
            if ref_conf is not None:
                try:
                    field_conf["ref_produit"] = max(0.0, min(1.0, float(ref_conf)))
                except (TypeError, ValueError):
                    pass
            if des_conf is not None:
                try:
                    field_conf["designation"] = max(0.0, min(1.0, float(des_conf)))
                except (TypeError, ValueError):
                    pass
            line_conf_val = min(
                field_conf.get("ref_produit", 1.0),
                field_conf.get("designation", 1.0),
                0.85 if ln.get("ocr_issues_detected") else 1.0,
            )

            lines.append(LineItemSchema(
                line_number=ln.get("line_number", i + 1),
                ref_produit=normalize_reference(raw_ref) or None,
                ref_produit_normalized=normalize_reference(raw_ref) or None,
                designation=await word_dictionary.normalize_text(raw_des, field_name="designation"),
                qty=qty_val,
                unit=ln.get("unit"),
                prix_unitaire=prix_val,
                tva_rate=normalize_number(str(ln["tva_rate"])) if ln.get("tva_rate") is not None else None,
                total_ligne_ht=total_val,
                raw_reference=raw_ref or None,
                raw_designation=raw_des or None,
                raw_qty=qty_raw or None,
                raw_unit_price=prix_raw or None,
                raw_total=total_raw or None,
                reference_confidence=field_conf.get("ref_produit", 1.0),
                designation_confidence=field_conf.get("designation", 1.0),
                line_confidence=line_conf_val,
                field_confidence_map=field_conf,
                extraction_confidence=line_conf_val,
                has_low_confidence=line_conf_val < 0.70 or bool(ln.get("ocr_issues_detected")),
            ))

        # Strip non-product lines before building the schema
        lines = [ln for ln in lines if _is_valid_product_line(ln)]

        if doc_type == DocumentType.BC:
            return BonDeCommandeSchema(
                ref_bc=normalize_reference(raw["ref_bc"]),
                document_date=normalize_date(raw.get("document_date")),
                supplier_name=normalize_text(raw.get("supplier_name", "")),
                lines=lines,
                extraction_source_tier=ExtractionTier.LLM,
                extraction_confidence=0.70,
            )
        elif doc_type == DocumentType.BL:
            return BonDeLivraison(
                ref_bl=normalize_reference(raw["ref_bl"]),
                ref_bc_linked=_safe_normalize_ref(raw.get("ref_bc_linked")),
                document_date=normalize_date(raw.get("document_date")),
                supplier_name=normalize_text(raw.get("supplier_name", "")),
                lines=lines,
                extraction_source_tier=ExtractionTier.LLM,
                extraction_confidence=0.70,
            )
        elif doc_type == DocumentType.FACTURE:
            return FactureSchema(
                ref_facture=normalize_reference(raw["ref_facture"]),
                ref_bc_linked=_safe_normalize_ref(raw.get("ref_bc_linked")),
                document_date=normalize_date(raw.get("document_date")),
                supplier_name=normalize_text(raw.get("supplier_name", "")),
                total_ht=normalize_number(str(raw["total_ht"])) if raw.get("total_ht") else None,
                total_ttc=normalize_number(str(raw["total_ttc"])) if raw.get("total_ttc") else None,
                tva_rate=normalize_number(str(raw["tva_rate"])) if raw.get("tva_rate") else None,
                lines=lines,
                extraction_source_tier=ExtractionTier.LLM,
                extraction_confidence=0.70,
            )
    except (KeyError, TypeError, Exception) as e:
        logger.error("llm_schema_mapping_failed doc_type=%s error=%s", doc_type, str(e))
        return None

