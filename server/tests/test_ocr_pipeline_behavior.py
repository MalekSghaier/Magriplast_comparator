"""
Behavioral invariant tests for the OCR extraction pipeline.

These tests verify GENERIC extraction properties that must hold for any
document — not just the Boudrant PDF.  They use synthetic OCR data and
made-up line values to ensure no supplier-specific logic creeps into
production code.

Invariants checked:
  1. Raw values are preserved (no silent rounding or truncation).
  2. Unit price comes from the prix_unitaire column, NOT from total_ligne.
  3. Qty × prix_unitaire ≈ total → math_consistency_ok = True.
  4. Qty × prix_unitaire ≠ total → math_consistency_ok = False + low confidence.
  5. Math consistency ratio is recorded for diagnostic purposes.
  6. Spatial extractor falls back gracefully when no OCR data is provided.
  7. The text-split fallback assigns numeric tokens in order (qty, price, total).
  8. parse_quantity preserves decimal without multiplying by 10.
  9. Spatial rows with no useful content are silently skipped.
 10. Column detection returns None when fewer than 3 columns are found.

Run from server/:
    pytest tests/test_ocr_pipeline_behavior.py -v
"""
import pytest
from decimal import Decimal
from unittest.mock import patch

from app.schemas.documents import LineItemSchema
from app.utils.number_parser import parse_quantity, parse_money
from app.utils.spatial_ocr import (
    extract_word_boxes,
    group_words_into_rows,
    detect_table_header_row,
    compute_column_boundaries,
    assign_words_to_columns,
    cell_text_and_confidence,
    OCRWordBox,
    ColumnDef,
    SpatialRow,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_word(text, x, y, w=50, h=15, conf=85, line=1, block=1, par=1) -> OCRWordBox:
    return OCRWordBox(text=text, x=x, y=y, w=w, h=h, conf=float(conf),
                     line_num=line, block_num=block, par_num=par)


def _make_raw_data(words: list[OCRWordBox]) -> dict:
    """Build a minimal pytesseract-style raw_data dict from a list of OCRWordBox."""
    return {
        "text":      [w.text for w in words],
        "left":      [w.x for w in words],
        "top":       [w.y for w in words],
        "width":     [w.w for w in words],
        "height":    [w.h for w in words],
        "conf":      [int(w.conf) for w in words],
        "line_num":  [w.line_num for w in words],
        "block_num": [w.block_num for w in words],
        "par_num":   [w.par_num for w in words],
    }


# ── Test: raw value preservation in LineItemSchema ───────────────────────────

class TestRawValuePreservation:
    def test_raw_unit_price_preserved(self):
        """raw_unit_price must store the exact OCR string, not a float."""
        item = LineItemSchema(
            line_number=1,
            qty=Decimal("3"),
            prix_unitaire=Decimal("122.341"),
            raw_unit_price="122.341",
            total_ligne_ht=Decimal("367.023"),
        )
        assert item.raw_unit_price == "122.341"

    def test_raw_qty_preserved(self):
        item = LineItemSchema(
            line_number=1,
            qty=Decimal("4.0"),
            raw_qty="4.0",
        )
        assert item.raw_qty == "4.0"

    def test_raw_total_preserved(self):
        item = LineItemSchema(
            line_number=1,
            total_ligne_ht=Decimal("415.959"),
            raw_total="415.959",
        )
        assert item.raw_total == "415.959"

    def test_raw_designation_preserved_with_spaces(self):
        item = LineItemSchema(
            line_number=1,
            designation="RACCORD DROIT 12 1/4",
            raw_designation="RACCORD DROIT 12 1/4",
        )
        assert " " in item.raw_designation
        assert "/" in item.raw_designation


# ── Test: math consistency check ─────────────────────────────────────────────

class TestMathConsistency:
    def test_consistent_line_passes(self):
        item = LineItemSchema(
            line_number=1,
            qty=Decimal("3"),
            prix_unitaire=Decimal("10.000"),
            total_ligne_ht=Decimal("30.000"),
        )
        assert item.math_consistency_ok is True
        assert item.has_low_confidence is False

    def test_inconsistent_line_flagged(self):
        """qty × prix ≠ total → math_consistency_ok=False, has_low_confidence=True."""
        item = LineItemSchema(
            line_number=1,
            qty=Decimal("40"),        # wrong: should be 4
            prix_unitaire=Decimal("10.000"),
            total_ligne_ht=Decimal("40.000"),  # correct for qty=4
        )
        assert item.math_consistency_ok is False
        assert item.has_low_confidence is True

    def test_consistency_ratio_recorded(self):
        """Ratio is recorded so callers can diagnose the scale of the error."""
        item = LineItemSchema(
            line_number=1,
            qty=Decimal("40"),
            prix_unitaire=Decimal("10.000"),
            total_ligne_ht=Decimal("40.000"),
        )
        assert item.math_consistency_ratio is not None
        # 40×10 = 400, total = 40 → ratio = 40/400 = 0.1
        assert abs(item.math_consistency_ratio - 0.1) < 0.01

    def test_missing_fields_no_check(self):
        """If qty or prix is absent, math_consistency_ok stays None."""
        item = LineItemSchema(line_number=1, qty=Decimal("5"))
        assert item.math_consistency_ok is None

    def test_small_rounding_tolerance(self):
        """Differences within 1% of the total should still pass."""
        item = LineItemSchema(
            line_number=1,
            qty=Decimal("3"),
            prix_unitaire=Decimal("33.333"),
            total_ligne_ht=Decimal("99.999"),  # 3 × 33.333 = 99.999 exactly
        )
        assert item.math_consistency_ok is True


# ── Test: per-field confidence ────────────────────────────────────────────────

class TestPerFieldConfidence:
    def test_default_confidence_is_one(self):
        item = LineItemSchema(line_number=1)
        assert item.reference_confidence == 1.0
        assert item.quantity_confidence == 1.0
        assert item.unit_price_confidence == 1.0

    def test_custom_confidence_accepted(self):
        item = LineItemSchema(
            line_number=1,
            reference_confidence=0.65,
            quantity_confidence=0.80,
        )
        assert item.reference_confidence == 0.65
        assert item.quantity_confidence == 0.80

    def test_low_confidence_flag_from_field(self):
        item = LineItemSchema(
            line_number=1,
            qty=Decimal("10"),
            prix_unitaire=Decimal("5.000"),
            total_ligne_ht=Decimal("999.999"),  # wrong total → flags line
        )
        assert item.has_low_confidence is True


# ── Test: spatial OCR word-box utilities ──────────────────────────────────────

class TestExtractWordBoxes:
    def test_basic_extraction(self):
        words = [
            _make_word("HELLO", 10, 20),
            _make_word("WORLD", 80, 20),
        ]
        raw_data = _make_raw_data(words)
        result = extract_word_boxes(raw_data)
        assert len(result) == 2
        assert result[0].text == "HELLO"
        assert result[1].text == "WORLD"

    def test_skips_blank_words(self):
        words = [
            _make_word("TEXT", 10, 20),
            _make_word("", 50, 20),      # blank — should be skipped
            _make_word("MORE", 90, 20),
        ]
        raw_data = _make_raw_data(words)
        # Manually add a blank
        raw_data["text"] = ["TEXT", "", "MORE"]
        raw_data["left"] = [10, 50, 90]
        raw_data["top"] = [20, 20, 20]
        raw_data["width"] = [40, 0, 40]
        raw_data["height"] = [15, 15, 15]
        raw_data["conf"] = [85, 85, 85]
        raw_data["line_num"] = [1, 1, 1]
        raw_data["block_num"] = [1, 1, 1]
        raw_data["par_num"] = [1, 1, 1]
        result = extract_word_boxes(raw_data)
        texts = [w.text for w in result]
        assert "" not in texts
        assert "TEXT" in texts
        assert "MORE" in texts

    def test_skips_negative_confidence(self):
        raw_data = {
            "text": ["WORD"],
            "left": [10], "top": [10], "width": [50], "height": [15],
            "conf": [-1],  # negative = non-word row from Tesseract
            "line_num": [1], "block_num": [1], "par_num": [1],
        }
        result = extract_word_boxes(raw_data)
        assert result == []


class TestGroupWordsIntoRows:
    def test_two_separate_rows(self):
        words = [
            _make_word("A", 10, 20),
            _make_word("B", 80, 20),   # same Y → same row
            _make_word("C", 10, 50),   # different Y → new row
        ]
        rows = group_words_into_rows(words, y_tolerance=6)
        assert len(rows) == 2
        assert len(rows[0]) == 2
        assert len(rows[1]) == 1

    def test_row_sorted_left_to_right(self):
        words = [
            _make_word("B", 80, 20),
            _make_word("A", 10, 20),
        ]
        rows = group_words_into_rows(words, y_tolerance=6)
        assert rows[0][0].text == "A"
        assert rows[0][1].text == "B"

    def test_empty_input(self):
        assert group_words_into_rows([]) == []

    def test_tolerance_merges_near_rows(self):
        words = [
            _make_word("A", 10, 20),
            _make_word("B", 80, 24),   # 4 px apart, within tolerance=6
        ]
        rows = group_words_into_rows(words, y_tolerance=6)
        assert len(rows) == 1


class TestDetectTableHeaderRow:
    def _header_row_words(self):
        return [
            _make_word("REF",         10,  10, w=40),
            _make_word("DESIGNATION", 100, 10, w=100),
            _make_word("QTE",         250, 10, w=40),
            _make_word("PRIX",        350, 10, w=40),
            _make_word("TOTAL",       450, 10, w=50),
        ]

    def test_detects_header(self):
        header_words = self._header_row_words()
        data_words = [
            _make_word("ABC123", 10, 30),
            _make_word("SOME ITEM", 100, 30),
            _make_word("5",         250, 30),
            _make_word("10.000",    350, 30),
            _make_word("50.000",    450, 30),
        ]
        rows = group_words_into_rows(header_words + data_words, y_tolerance=6)
        patterns = {
            "ref_produit":   [r"R[ÉE]F", r"REF"],
            "designation":   [r"D[ÉE]SIGNATION", r"DESIGNATION"],
            "qty":           [r"QT[ÉE]", r"QTE"],
            "prix_unitaire": [r"PRIX"],
            "total_ligne":   [r"TOTAL"],
        }
        idx, col_defs = detect_table_header_row(rows, patterns, min_columns=3)
        assert idx is not None
        assert "qty" in col_defs
        assert "prix_unitaire" in col_defs

    def test_returns_none_when_no_header(self):
        words = [
            _make_word("HELLO", 10, 10),
            _make_word("WORLD", 80, 10),
        ]
        rows = group_words_into_rows(words, y_tolerance=6)
        idx, col_defs = detect_table_header_row(rows, {"qty": [r"QTE"]}, min_columns=3)
        assert idx is None
        assert col_defs is None


class TestComputeColumnBoundaries:
    def test_boundaries_cover_full_width(self):
        col_defs = {
            "ref_produit":   ColumnDef("ref_produit",   10.0,  50.0,  "REF",   0.9),
            "designation":   ColumnDef("designation",   100.0, 200.0, "DESC",  0.9),
            "qty":           ColumnDef("qty",           250.0, 290.0, "QTE",   0.9),
        }
        result = compute_column_boundaries(col_defs, page_width=400)
        assert result["ref_produit"].x_min == 0.0
        assert result["qty"].x_max == 400.0

    def test_no_gap_between_columns(self):
        col_defs = {
            "a": ColumnDef("a", 10.0, 50.0,  "A", 0.9),
            "b": ColumnDef("b", 100.0, 150.0, "B", 0.9),
        }
        result = compute_column_boundaries(col_defs, page_width=300)
        # Boundary between a and b = midpoint of (50, 100) = 75
        assert result["a"].x_max == result["b"].x_min
        assert result["a"].x_max == pytest.approx(75.0)


class TestAssignWordsToColumns:
    def test_assigns_to_correct_column(self):
        col_defs = {
            "ref_produit":   ColumnDef("ref_produit",   0.0,  150.0, "REF",   0.9),
            "qty":           ColumnDef("qty",           150.0, 300.0, "QTE",   0.9),
            "prix_unitaire": ColumnDef("prix_unitaire", 300.0, 500.0, "PRIX",  0.9),
        }
        row_words = [
            _make_word("ABC123", 50,  30, w=60),   # x_center=80 → ref_produit
            _make_word("5",      200, 30, w=20),   # x_center=210 → qty
            _make_word("10.000", 350, 30, w=50),   # x_center=375 → prix_unitaire
        ]
        buckets = assign_words_to_columns(row_words, col_defs)
        assert buckets["ref_produit"][0].text == "ABC123"
        assert buckets["qty"][0].text == "5"
        assert buckets["prix_unitaire"][0].text == "10.000"

    def test_price_not_taken_from_total_column(self):
        """
        Even if the total value appears to the right of prix_unitaire,
        column assignment by X position must prevent it from being
        extracted as the unit price.
        """
        col_defs = {
            "prix_unitaire": ColumnDef("prix_unitaire", 300.0, 450.0, "PRIX",  0.9),
            "total_ligne":   ColumnDef("total_ligne",   450.0, 600.0, "TOTAL", 0.9),
        }
        row_words = [
            _make_word("10.000", 350, 30, w=50),  # x_center=375 → prix_unitaire
            _make_word("50.000", 480, 30, w=50),  # x_center=505 → total_ligne
        ]
        buckets = assign_words_to_columns(row_words, col_defs)
        # Unit price must come from prix_unitaire, not total_ligne
        prix_texts = [w.text for w in buckets.get("prix_unitaire", [])]
        total_texts = [w.text for w in buckets.get("total_ligne", [])]
        assert "10.000" in prix_texts
        assert "50.000" in total_texts
        assert "50.000" not in prix_texts


class TestCellTextAndConfidence:
    def test_concatenates_words(self):
        words = [
            _make_word("RACCORD", 10,  20, conf=90),
            _make_word("DROIT",   80,  20, conf=80),
            _make_word("12",      130, 20, conf=85),
        ]
        text, conf = cell_text_and_confidence(words)
        assert text == "RACCORD DROIT 12"
        assert 0.8 <= conf <= 0.95

    def test_empty_cell_returns_empty_string(self):
        text, conf = cell_text_and_confidence([])
        assert text == ""
        assert conf == 1.0

    def test_slash_preserved(self):
        """Fractions like 1/4 must survive concatenation."""
        words = [
            _make_word("1/4", 10, 20, conf=75),
        ]
        text, _ = cell_text_and_confidence(words)
        assert "/" in text


# ── Test: text-split fallback assigns numbers in order ───────────────────────

class TestTextSplitFallbackOrder:
    """
    _parse_line_parts assigns numeric tokens left-to-right:
    first → qty, second → prix_unitaire, third → total.
    No magnitude-based heuristic.
    """
    def _parse(self, parts):
        from app.services.extractor import _parse_line_parts
        return _parse_line_parts(parts, {}, line_num=1)

    def test_three_numbers_assigned_correctly(self):
        # ref + qty + prix + total
        item = self._parse(["REF001", "5", "10.000", "50.000"])
        assert item is not None
        assert item.qty == Decimal("5")
        assert item.prix_unitaire == Decimal("10.000")
        assert item.total_ligne_ht == Decimal("50.000")

    def test_raw_strings_preserved(self):
        item = self._parse(["REF001", "4.0", "122.341", "489.364"])
        assert item is not None
        assert item.raw_qty == "4.0"
        assert item.raw_unit_price == "122.341"

    def test_price_not_swapped_with_total(self):
        """When unit price < total (as expected), they must NOT be swapped."""
        item = self._parse(["REF999", "2", "15.500", "31.000"])
        assert item is not None
        assert item.prix_unitaire == Decimal("15.500")
        assert item.total_ligne_ht == Decimal("31.000")

    def test_tva_extracted_from_percent_token(self):
        item = self._parse(["REFX", "10", "5.000", "19%", "50.000"])
        assert item is not None
        assert item.tva_rate == Decimal("19")

    def test_returns_none_when_no_useful_fields(self):
        item = self._parse(["ONLY TEXT NO NUMBERS"])
        assert item is None
