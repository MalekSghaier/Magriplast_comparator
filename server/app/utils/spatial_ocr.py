"""
Spatial OCR utilities: reconstruct table structure from word bounding boxes.

Instead of splitting raw OCR text by whitespace (which loses column boundaries),
these utilities use the (x, y, width, height) coordinates that Tesseract outputs
per word to:
  1. Group words into visual rows by Y proximity
  2. Detect table column headers by matching keyword patterns
  3. Extend each header's X range to the midpoint between adjacent headers
  4. Assign every word in a data row to its column by X position
  5. Return per-column text with an averaged OCR confidence score

No hardcoded references, designations, quantities, or prices are used.
Column layout is inferred dynamically per document.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Word-level representation ─────────────────────────────────────────────────

@dataclass
class OCRWordBox:
    """A single OCR word with its bounding box and confidence."""
    text: str
    x: int       # left edge (pixels)
    y: int       # top edge (pixels)
    w: int       # width (pixels)
    h: int       # height (pixels)
    conf: float  # Tesseract confidence 0-100
    line_num: int
    block_num: int
    par_num: int

    @property
    def x_center(self) -> float:
        return self.x + self.w / 2.0

    @property
    def y_center(self) -> float:
        return self.y + self.h / 2.0

    @property
    def x_right(self) -> int:
        return self.x + self.w


# ── Column definition ─────────────────────────────────────────────────────────

@dataclass
class ColumnDef:
    """A detected table column with its logical name and X boundaries."""
    name: str          # logical name: ref_produit | designation | qty | unit | prix_unitaire | tva_rate | total_ligne
    x_min: float       # left boundary (pixels)
    x_max: float       # right boundary (pixels)
    header_text: str   # the matched header text as read by OCR
    header_confidence: float  # 0-1


# ── Raw-data to word boxes ────────────────────────────────────────────────────

def extract_word_boxes(raw_data: dict) -> list[OCRWordBox]:
    """
    Convert a pytesseract image_to_data dict to a list of OCRWordBox.
    Skips words with negative confidence (non-word rows from Tesseract) and
    words that are blank after stripping.
    """
    words: list[OCRWordBox] = []
    texts = raw_data.get("text", [])
    for i, text in enumerate(texts):
        if not text or not text.strip():
            continue
        conf = int(raw_data["conf"][i])
        if conf < 0:
            continue
        words.append(OCRWordBox(
            text=text.strip(),
            x=int(raw_data["left"][i]),
            y=int(raw_data["top"][i]),
            w=int(raw_data["width"][i]),
            h=int(raw_data["height"][i]),
            conf=float(conf),
            line_num=int(raw_data.get("line_num", [0] * len(texts))[i]),
            block_num=int(raw_data.get("block_num", [0] * len(texts))[i]),
            par_num=int(raw_data.get("par_num", [0] * len(texts))[i]),
        ))
    return words


# ── Row grouping ──────────────────────────────────────────────────────────────

def group_words_into_rows(
    words: list[OCRWordBox],
    y_tolerance: int = 6,
) -> list[list[OCRWordBox]]:
    """
    Cluster OCR words into visual rows using the Y center of the FIRST word
    in each row as the fixed anchor (not a rolling average).

    Using the first word as anchor prevents drift in long rows where many
    words at slightly different heights would progressively shift the average
    and pull in words from the next row.

    y_tolerance=6 px is correct for 300–400 DPI scans. Increase to 10–12 for
    low-resolution input or documents that still have residual skew after
    preprocessing.
    """
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: w.y_center)
    rows: list[list[OCRWordBox]] = []
    current_row: list[OCRWordBox] = [sorted_words[0]]
    # anchor = Y center of the FIRST word in the row (fixed for the row's lifetime)
    row_anchor_y: float = sorted_words[0].y_center

    for w in sorted_words[1:]:
        if abs(w.y_center - row_anchor_y) <= y_tolerance:
            current_row.append(w)
            # anchor stays fixed — do NOT update it
        else:
            rows.append(sorted(current_row, key=lambda ww: ww.x))
            current_row = [w]
            row_anchor_y = w.y_center   # new anchor for the new row

    if current_row:
        rows.append(sorted(current_row, key=lambda ww: ww.x))

    return rows


# ── Column detection ──────────────────────────────────────────────────────────

def detect_table_header_row(
    rows: list[list[OCRWordBox]],
    column_patterns: dict[str, list[str]],
    min_columns: int = 3,
    search_rows: int = 120,   # was 40 — A4 at 400 DPI has 100+ word rows
) -> tuple[Optional[int], Optional[dict[str, ColumnDef]]]:
    """
    Scan rows for the table header line.

    Two-pass strategy:
    Pass 1: require min_columns matches (default 3) — high-confidence detection.
    Pass 2: if pass 1 fails, lower the bar to 2 columns — handles tables where
            a column header was missed by OCR (e.g. smudged "Désignation" header).

    Multi-word headers (e.g. "PRIX UNIT.") are handled by scanning
    combinations of consecutive words within a row.

    Returns (row_index, {col_name: ColumnDef}) or (None, None).
    """
    def _scan(min_cols: int) -> tuple[Optional[int], Optional[dict[str, ColumnDef]]]:
        for row_idx, row_words in enumerate(rows[:search_rows]):
            found: dict[str, ColumnDef] = {}
            for col_name, patterns in column_patterns.items():
                if col_name in found:
                    continue
                for span_len in (1, 2, 3):
                    if col_name in found:
                        break
                    for start in range(len(row_words) - span_len + 1):
                        span_words = row_words[start : start + span_len]
                        span_text = " ".join(w.text for w in span_words).upper()
                        for pattern in patterns:
                            if re.search(pattern, span_text):
                                x_min = span_words[0].x
                                x_max = span_words[-1].x_right
                                avg_conf = (
                                    sum(w.conf for w in span_words) / len(span_words)
                                )
                                found[col_name] = ColumnDef(
                                    name=col_name,
                                    x_min=float(x_min),
                                    x_max=float(x_max),
                                    header_text=span_text.strip(),
                                    header_confidence=avg_conf / 100.0,
                                )
                                break
                        if col_name in found:
                            break
            if len(found) >= min_cols:
                return row_idx, found
        return None, None

    # Pass 1: strict (min_columns)
    row_idx, found = _scan(min_columns)
    if row_idx is not None:
        return row_idx, found

    # Pass 2: relaxed (2 columns minimum) — catches tables with one OCR-missed header
    if min_columns > 2:
        return _scan(2)

    return None, None


def compute_column_boundaries(
    col_defs: dict[str, ColumnDef],
    page_width: int = 2480,
) -> dict[str, ColumnDef]:
    """
    Extend each column's X range to fill the space between adjacent columns.

    After detecting header positions, each column's x_min/x_max only covers
    the header word itself. This function expands boundaries so that every
    pixel belongs to exactly one column (no dead zones between columns).

    Columns are sorted by their header x_min. The left edge of the first
    column starts at 0; the right edge of the last column ends at page_width.
    Between adjacent columns, the boundary is at the midpoint of their gap.
    """
    if not col_defs:
        return {}

    sorted_cols = sorted(col_defs.values(), key=lambda c: c.x_min)
    result: dict[str, ColumnDef] = {}

    for i, col in enumerate(sorted_cols):
        left = 0.0 if i == 0 else (sorted_cols[i - 1].x_max + col.x_min) / 2.0
        right = float(page_width) if i == len(sorted_cols) - 1 else (col.x_max + sorted_cols[i + 1].x_min) / 2.0
        result[col.name] = ColumnDef(
            name=col.name,
            x_min=left,
            x_max=right,
            header_text=col.header_text,
            header_confidence=col.header_confidence,
        )
    return result


# ── Row → column cell extraction ─────────────────────────────────────────────

def assign_words_to_columns(
    row_words: list[OCRWordBox],
    col_defs: dict[str, ColumnDef],
) -> dict[str, list[OCRWordBox]]:
    """
    Assign each word in a row to the column whose X range contains it.
    Uses the word's X center for assignment.
    Returns a dict of col_name → [words in that column, left-to-right].
    """
    buckets: dict[str, list[OCRWordBox]] = {name: [] for name in col_defs}
    for word in row_words:
        for col_name, col in col_defs.items():
            if col.x_min <= word.x_center < col.x_max:
                buckets[col_name].append(word)
                break
    return buckets


def cell_text_and_confidence(
    words: list[OCRWordBox],
) -> tuple[str, float]:
    """
    Concatenate words in a cell (left-to-right) with a single space separator.
    Returns (text, avg_confidence_0_to_1).
    Empty cell → ("", 1.0) — absence of text is not an OCR error.
    """
    if not words:
        return "", 1.0
    sorted_words = sorted(words, key=lambda w: w.x)
    text = " ".join(w.text for w in sorted_words)
    avg_conf = sum(w.conf for w in sorted_words) / len(sorted_words) / 100.0
    return text, avg_conf


# ── Table stop-row detection ──────────────────────────────────────────────────

_TABLE_STOP_PATTERNS = [
    # HT total row — matches "TOTAL H.T", "TOTAL HT", "MONTANT H.T", "MONTANT HT"
    r"(?:TOTAL|MONTANT)\s+H\.?\s*T\.?(?:\s*:)?",
    # TTC total
    r"(?:TOTAL|MONTANT)\s+T\.?\s*T\.?\s*C\.?",
    # Net to pay
    r"NET\s+[AÀ]\s+PAYER",
    r"NET\s+HORS\s+TAXES",
    # TVA summary rows — match "BASE T.V.A", "MONTANT T.V.A", "TOTAL TVA"
    r"(?:BASE|MONTANT|TOTAL)\s+T\.?\s*V\.?\s*A\.?",
    # Sub-total
    r"SOUS.TOTAL",
    r"TOTAL\s+G[EÉ]N[EÉ]RAL",
    # Tunisian invoice closing statement
    r"ARRET[EÉE]+\s+(?:LA\s+)?PR[EÉ]SENT",
    # FODEC and TIMBRE always appear in footer blocks
    r"\bFODEC\b",
    r"\bTIMBRE\b",
    # "REMISE HORS TAXES" only in footer — bare "REMISE" intentionally excluded
    # as it appears as a column header in BC tables
    r"REMISE\s+HORS\s+TAXES",
]


def is_table_stop_row(row_words: list[OCRWordBox]) -> bool:
    """Return True if this row marks the end of the line-item table."""
    row_text = " ".join(w.text for w in row_words).upper()
    return any(re.search(p, row_text) for p in _TABLE_STOP_PATTERNS)


def row_has_numeric_content(row_words: list[OCRWordBox]) -> bool:
    """Return True if the row contains at least one numeric token."""
    for w in row_words:
        cleaned = re.sub(r"[,.\s]", "", w.text)
        if cleaned.isdigit() and len(cleaned) >= 1:
            return True
    return False


# ── Combined extraction ───────────────────────────────────────────────────────

@dataclass
class SpatialRow:
    """
    One data row extracted by spatial analysis.
    Contains raw text per logical column and per-column confidence.
    """
    raw_ref: str = ""
    raw_designation: str = ""
    raw_qty: str = ""
    raw_unit: str = ""
    raw_unit_price: str = ""
    raw_tva: str = ""
    raw_total: str = ""

    ref_confidence: float = 1.0
    designation_confidence: float = 1.0
    qty_confidence: float = 1.0
    unit_price_confidence: float = 1.0
    tva_confidence: float = 1.0
    total_confidence: float = 1.0

    row_word_count: int = 0


def extract_spatial_rows(
    raw_data: dict,
    column_patterns: dict[str, list[str]],
    y_tolerance: int = 6,
    min_columns: int = 3,
) -> list[SpatialRow]:
    """
    Full spatial extraction pipeline for one page's OCR data.

    Steps:
      1. Convert raw pytesseract dict → OCRWordBox list
      2. Group words into rows by Y proximity
      3. Find the table header row using column_patterns
      4. Extend column boundaries to fill the page width
      5. For each data row after the header:
         - Assign words to columns
         - Extract cell text + confidence
         - Stop at table-stop keywords
    Returns a list of SpatialRow (one per data row found).
    """
    words = extract_word_boxes(raw_data)
    if not words:
        return []

    page_width = max(w.x_right for w in words) + 10

    rows = group_words_into_rows(words, y_tolerance=y_tolerance)
    header_idx, raw_col_defs = detect_table_header_row(
        rows, column_patterns, min_columns=min_columns
    )
    if header_idx is None or raw_col_defs is None:
        return []

    col_defs = compute_column_boundaries(raw_col_defs, page_width=page_width)

    spatial_rows: list[SpatialRow] = []
    for row_words in rows[header_idx + 1:]:
        if not row_words:
            continue
        if is_table_stop_row(row_words):
            break
        if not row_has_numeric_content(row_words):
            continue

        buckets = assign_words_to_columns(row_words, col_defs)

        ref_text, ref_conf = cell_text_and_confidence(buckets.get("ref_produit", []))
        des_text, des_conf = cell_text_and_confidence(buckets.get("designation", []))
        qty_text, qty_conf = cell_text_and_confidence(buckets.get("qty", []))
        unit_text, _ = cell_text_and_confidence(buckets.get("unit", []))
        prix_text, prix_conf = cell_text_and_confidence(buckets.get("prix_unitaire", []))
        tva_text, tva_conf = cell_text_and_confidence(buckets.get("tva_rate", []))
        total_text, total_conf = cell_text_and_confidence(buckets.get("total_ligne", []))
        if not any([ref_text, des_text, qty_text, prix_text, total_text]):
            continue

        spatial_rows.append(SpatialRow(
            raw_ref=ref_text,
            raw_designation=des_text,
            raw_qty=qty_text,
            raw_unit=unit_text,
            raw_unit_price=prix_text,
            raw_tva=tva_text,
            raw_total=total_text,
            ref_confidence=ref_conf,
            designation_confidence=des_conf,
            qty_confidence=qty_conf,
            unit_price_confidence=prix_conf,
            tva_confidence=tva_conf,
            total_confidence=total_conf,
            row_word_count=len(row_words),
        ))

    return spatial_rows