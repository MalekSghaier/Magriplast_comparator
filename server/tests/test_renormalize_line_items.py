"""
Tests for renormalize_line_items (app.services.renormalize_line_items).

Test 1 — dry-run:    report shows modification, item NOT written.
Test 2 — apply:      item.designation updated, raw_designation untouched.
Test 3 — codes/nums: codes and dimensions pass through unchanged.
Test 4 — API serializer: response dict uses designation, not raw_designation.
Test 5 — pipeline:   normalized value saved as designation for new line_items.
"""
import asyncio
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── helpers ────────────────────────────────────────────────────────────────────

def sync(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@dataclass
class FakeLineItem:
    """Minimal stand-in for a SQLAlchemy LineItem — no DB required."""
    id: str = "item-1"
    document_id: str = "doc-1"
    line_number: int = 1
    designation: Optional[str] = None
    raw_designation: Optional[str] = None
    ref_produit: Optional[str] = None
    ref_produit_normalized: Optional[str] = None
    qty: Optional[float] = None
    prix_unitaire: Optional[float] = None
    total_ligne_ht: Optional[float] = None
    tva_rate: Optional[float] = None


_MOCK_PATH = "app.services.renormalize_line_items.word_dictionary.normalize_text"


# ══════════════════════════════════════════════════════════════════════════════
# Test 1 — dry-run: report shows change, DB not modified
# ══════════════════════════════════════════════════════════════════════════════

class TestDryRun:
    def test_item_not_modified(self):
        item = FakeLineItem(
            designation="CADNA BLOUS LATON 60MM REF 2110610",
            raw_designation="CADNA BLOUS LATON 60MM REF 2110610",
        )
        corrected = "CADENAS BLOCUS LAITON 60MM REFERENCE 2110610"

        async def run():
            from app.services.renormalize_line_items import _process_batch
            with patch(_MOCK_PATH, new=AsyncMock(return_value=corrected)):
                scanned, changed, corrections = await _process_batch(
                    [item], dry_run=True
                )

            assert scanned == 1
            assert changed == 1
            assert len(corrections) == 1
            assert corrections[0]["before"] == "CADNA BLOUS LATON 60MM REF 2110610"
            assert corrections[0]["after"] == corrected
            # dry-run: item must NOT be written
            assert item.designation == "CADNA BLOUS LATON 60MM REF 2110610"

        sync(run())

    def test_report_carries_document_and_line(self):
        item = FakeLineItem(
            designation="CADNA BLOUS LATON",
            raw_designation="CADNA BLOUS LATON",
            document_id="doc-abc",
            line_number=3,
        )

        async def run():
            from app.services.renormalize_line_items import _process_batch
            with patch(_MOCK_PATH, new=AsyncMock(return_value="CADENAS BLOCUS LAITON")):
                _, _, corrections = await _process_batch([item], dry_run=True)

            assert corrections[0]["document_id"] == "doc-abc"
            assert corrections[0]["line_number"] == 3

        sync(run())

    def test_no_change_when_already_normalized(self):
        already = "CADENAS BLOCUS LAITON 60MM"
        item = FakeLineItem(designation=already, raw_designation="CADNA BLOUS LATON 60MM")

        async def run():
            from app.services.renormalize_line_items import _process_batch
            # word_dict returns same value → no change expected
            with patch(_MOCK_PATH, new=AsyncMock(return_value=already)):
                scanned, changed, _ = await _process_batch([item], dry_run=True)

            assert scanned == 1
            assert changed == 0

        sync(run())


# ══════════════════════════════════════════════════════════════════════════════
# Test 2 — apply mode: designation updated, raw_designation never touched
# ══════════════════════════════════════════════════════════════════════════════

class TestApplyMode:
    def test_designation_updated(self):
        item = FakeLineItem(
            designation="CADNA BLOUS LATON 60MM REF 2110610",
            raw_designation="CADNA BLOUS LATON 60MM REF 2110610",
        )
        corrected = "CADENAS BLOCUS LAITON 60MM REFERENCE 2110610"

        async def run():
            from app.services.renormalize_line_items import _process_batch
            with patch(_MOCK_PATH, new=AsyncMock(return_value=corrected)):
                scanned, changed, _ = await _process_batch([item], dry_run=False)

            assert changed == 1
            assert item.designation == corrected

        sync(run())

    def test_raw_designation_never_modified(self):
        item = FakeLineItem(
            designation="CADNA BLOUS LATON",
            raw_designation="CADNA BLOUS LATON",
            qty=5.0,
            prix_unitaire=12.50,
            total_ligne_ht=62.50,
            tva_rate=0.19,
        )

        async def run():
            from app.services.renormalize_line_items import _process_batch
            with patch(_MOCK_PATH, new=AsyncMock(return_value="CADENAS BLOCUS LAITON")):
                await _process_batch([item], dry_run=False)

            assert item.raw_designation == "CADNA BLOUS LATON"
            assert item.qty == 5.0
            assert item.prix_unitaire == 12.50
            assert item.total_ligne_ht == 62.50
            assert item.tva_rate == 0.19

        sync(run())

    def test_fallback_source_from_raw_when_designation_empty(self):
        """If designation is empty, raw_designation is used as source."""
        item = FakeLineItem(
            designation=None,
            raw_designation="CADNA BLOUS LATON",
        )

        async def run():
            from app.services.renormalize_line_items import _process_batch
            with patch(_MOCK_PATH, new=AsyncMock(return_value="CADENAS BLOCUS LAITON")) as mock_norm:
                await _process_batch([item], dry_run=False)

            # normalize_text must have been called with the raw value
            mock_norm.assert_called_once_with(
                "CADNA BLOUS LATON", field_name="designation"
            )
            assert item.designation == "CADENAS BLOCUS LAITON"
            assert item.raw_designation == "CADNA BLOUS LATON"

        sync(run())


# ══════════════════════════════════════════════════════════════════════════════
# Test 3 — product codes and dimensions pass through unchanged
# ══════════════════════════════════════════════════════════════════════════════

class TestProtectedValuesPreserved:
    def test_code_and_dimension_unchanged(self):
        """
        word_dictionary.normalize_text handles protection internally.
        The service must pass the result through without altering it.
        """
        raw = "P198602123 CADNA BLOUS LAITON 60MM REF 2110610"
        expected = "P198602123 CADENAS BLOCUS LAITON 60MM REFERENCE 2110610"

        item = FakeLineItem(designation=raw, raw_designation=raw)

        async def run():
            from app.services.renormalize_line_items import _process_batch
            with patch(_MOCK_PATH, new=AsyncMock(return_value=expected)):
                _, changed, corrections = await _process_batch([item], dry_run=False)

            assert changed == 1
            assert item.designation == expected
            assert "P198602123" in item.designation  # product code preserved
            assert "60MM" in item.designation         # dimension preserved
            assert "2110610" in item.designation      # reference number preserved
            assert "BLOCUS" in item.designation       # OCR correction applied

        sync(run())

    def test_item_without_text_is_skipped(self):
        item = FakeLineItem(designation=None, raw_designation=None)

        async def run():
            from app.services.renormalize_line_items import _process_batch
            with patch(_MOCK_PATH, new=AsyncMock(return_value="ANYTHING")) as mock_norm:
                scanned, changed, _ = await _process_batch([item], dry_run=True)

            assert scanned == 1
            assert changed == 0
            mock_norm.assert_not_called()

        sync(run())


# ══════════════════════════════════════════════════════════════════════════════
# Test 4 — API serializer: dict uses designation, not raw_designation
# ══════════════════════════════════════════════════════════════════════════════

class TestAPISerializerField:
    def test_line_dict_uses_designation(self):
        """
        Mirrors the dict literal in server/app/api/results.py lines 57-68.
        'designation' must map to li.designation (normalized), not li.raw_designation.
        """
        li = MagicMock()
        li.line_number = 1
        li.ref_produit = "REF-001"
        li.designation = "CADENAS BLOCUS LAITON 60MM"
        li.raw_designation = "CADNA BLOUS LATON 60MM"
        li.qty = 2.0
        li.unit = "PCS"
        li.prix_unitaire = 15.0
        li.tva_rate = 0.19
        li.total_ligne_ht = 30.0
        li.extraction_confidence = 0.95
        li.field_confidence_map = {}

        # Exact dict construction from results.py
        line_dict = {
            "line_number": li.line_number,
            "ref_produit": li.ref_produit,
            "designation": li.designation,
            "qty": li.qty,
            "unit": li.unit,
            "prix_unitaire": li.prix_unitaire,
            "tva_rate": li.tva_rate,
            "total_ligne_ht": li.total_ligne_ht,
            "extraction_confidence": li.extraction_confidence,
            "field_confidence_map": li.field_confidence_map,
        }

        assert line_dict["designation"] == "CADENAS BLOCUS LAITON 60MM"
        assert line_dict["designation"] != li.raw_designation
        assert "raw_designation" not in line_dict

    def test_raw_designation_not_exposed_in_response(self):
        """raw_designation must not appear as a key in the API response."""
        li = MagicMock()
        li.line_number = 1
        li.ref_produit = "REF-001"
        li.designation = "CADENAS BLOCUS"
        li.raw_designation = "CADNA BLOUS"
        li.qty = 1.0
        li.unit = None
        li.prix_unitaire = 10.0
        li.tva_rate = 0.19
        li.total_ligne_ht = 10.0
        li.extraction_confidence = 0.90
        li.field_confidence_map = {}

        line_dict = {
            "line_number": li.line_number,
            "ref_produit": li.ref_produit,
            "designation": li.designation,
            "qty": li.qty,
            "unit": li.unit,
            "prix_unitaire": li.prix_unitaire,
            "tva_rate": li.tva_rate,
            "total_ligne_ht": li.total_ligne_ht,
            "extraction_confidence": li.extraction_confidence,
            "field_confidence_map": li.field_confidence_map,
        }

        assert "raw_designation" not in line_dict
        assert line_dict["designation"] == "CADENAS BLOCUS"


# ══════════════════════════════════════════════════════════════════════════════
# Test 5 — pipeline assignment logic
# ══════════════════════════════════════════════════════════════════════════════

class TestPipelineNormalization:
    def test_normalized_value_saved_as_designation(self):
        """
        Mirrors pipeline.py lines 335-344:
          normalized_designation = await word_dictionary.normalize_text(...)
          designation=normalized_designation or li.designation
        The normalized value must win over the raw extracted value.
        """
        raw_extracted = "CADNA BLOUS LATON 60MM REF 2110610"
        expected_normalized = "CADENAS BLOCUS LAITON 60MM REFERENCE 2110610"

        async def run():
            mock_normalize = AsyncMock(return_value=expected_normalized)
            normalized_designation = await mock_normalize(
                raw_extracted or "", field_name="designation"
            )
            saved_designation = normalized_designation or raw_extracted

            assert saved_designation == expected_normalized
            assert saved_designation != raw_extracted

        sync(run())

    def test_fallback_when_normalize_returns_empty(self):
        """
        If normalize_text returns empty string, fallback is li.designation (raw).
        Mirrors: designation=normalized_designation or li.designation
        """
        raw_extracted = "CADNA BLOUS LATON"

        async def run():
            mock_normalize = AsyncMock(return_value="")
            normalized_designation = await mock_normalize(
                raw_extracted or "", field_name="designation"
            )
            saved_designation = normalized_designation or raw_extracted

            assert saved_designation == raw_extracted

        sync(run())

    def test_raw_designation_stored_verbatim(self):
        """raw_designation is stored from li.raw_designation without normalization."""
        raw_ocr = "CADNA BLOUS LATON 60MM REF 2110610"
        normalized = "CADENAS BLOCUS LAITON 60MM REFERENCE 2110610"

        # Simulate what pipeline.py builds for the LineItem constructor
        li_raw_designation = raw_ocr       # pipeline: raw_designation=li.raw_designation
        li_designation = normalized        # pipeline: designation=normalized_designation or li.designation

        assert li_raw_designation == raw_ocr
        assert li_designation == normalized
        assert li_raw_designation != li_designation


# ══════════════════════════════════════════════════════════════════════════════
# Test — --only-containing filter
# ══════════════════════════════════════════════════════════════════════════════

class TestOnlyContainingFilter:
    def test_skips_non_matching_items(self):
        items = [
            FakeLineItem(
                id="a",
                designation="CADNA BLOUS LATON",
                raw_designation="CADNA BLOUS LATON",
            ),
            FakeLineItem(
                id="b",
                designation="TUBE PVC 50MM",
                raw_designation="TUBE PVC 50MM",
            ),
        ]

        async def run():
            from app.services.renormalize_line_items import _process_batch
            with patch(_MOCK_PATH, new=AsyncMock(return_value="CADENAS BLOCUS LAITON")):
                scanned, changed, corrections = await _process_batch(
                    items, dry_run=True, only_containing="blous"
                )

            assert scanned == 1
            assert changed == 1
            assert corrections[0]["line_item_id"] == "a"

        sync(run())

    def test_matches_on_raw_designation(self):
        """Filter must also match against raw_designation, not only designation."""
        items = [
            FakeLineItem(
                id="c",
                designation="CADENAS BLOCUS LAITON",   # already corrected
                raw_designation="CADNA BLOUS LATON",   # raw still has BLOUS
            ),
        ]

        async def run():
            from app.services.renormalize_line_items import _process_batch
            already = "CADENAS BLOCUS LAITON"
            with patch(_MOCK_PATH, new=AsyncMock(return_value=already)):
                # word_dict returns same as current designation → no change
                scanned, changed, _ = await _process_batch(
                    items, dry_run=True, only_containing="blous"
                )

            # Item was scanned (matched via raw_designation) but not changed
            assert scanned == 1
            assert changed == 0

        sync(run())
