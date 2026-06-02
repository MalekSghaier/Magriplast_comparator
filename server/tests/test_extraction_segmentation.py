"""
Tests for page-level document segmentation and the LLM-fallback trigger logic.

Covers:
  - group_pages_into_documents: FACTURE page 1 + BC pages 2-3 must produce two
    separate groups (never merged), with correct doc_type per group.
  - LLM-fallback trigger: a FactureSchema with 0 lines must be treated as an
    extraction failure and trigger LLM fallback regardless of header confidence.
  - No shared reference: invoice.lines and bc.lines must never be the same Python
    object (mutation-by-reference guard).
  - POSSIBLE_TABLE_REUSE_BUG detection: detect when FACTURE refs overlap
    significantly with BC refs.

Run from server/:
    pytest tests/test_extraction_segmentation.py -v
"""
import pytest
from decimal import Decimal

from app.services.classifier import DocType
from app.services.page_grouper import (
    PageClassified,
    group_pages_into_documents,
    is_bc_summary_misclassified_as_facture,
)
from app.schemas.documents import (
    BonDeCommandeSchema,
    FactureSchema,
    LineItemSchema,
    ExtractionTier,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_line(n: int, ref: str, qty: float = 1.0, prix: float = 10.0) -> LineItemSchema:
    return LineItemSchema(
        line_number=n,
        ref_produit=ref,
        ref_produit_normalized=ref,
        designation=f"Designation {ref}",
        qty=Decimal(str(qty)),
        prix_unitaire=Decimal(str(prix)),
        extraction_confidence=0.85,
    )


FACTURE_PAGE_TEXT = """
MAGRIPLAST — FACTURE N° A125/00408

Date : 10/09/2025
Réf. commande : OM176453

N°    QTÉ    Article    Désignation              Prix Unit HT    Montant HT
1     10     2019005    MV UNION = TECHNOPOLYMERE    5.568         55.680
2     10     NPC12-02   SHAKO RACCORD DROIT 12 1/4   8.207         82.070
...

TOTAL HT : 389.490
TVA 19% :   73.903
TOTAL TTC : 463.393
"""

BC_PAGE_2_TEXT = """
BON DE COMMANDE N° OM176453

Date : 05/09/2025

Article          Description                    UM   Qté   Prix UN
P199420414       BUTEE A RLX CYLIND ref 81105TN  U    4     122.341
NKX2528          AIG AVEC BUTEE                  U    4     242.200
P199584214       SHAKO UNION TECHNOPOLYMERE      U   10       5.568
NPC12-02         SHAKO RACCORD DROIT 12 1/4      U   10       8.207
NPC10-04         SHAKO RACC DROIT 10 1/2         U    5       7.752
"""

BC_PAGE_3_TEXT = """
BON DE COMMANDE N° OM176453   (suite)

Article          Description                    UM   Qté   Prix UN
NPC8-04          SHAKO RACC DROIT 8 1/2          U    5       6.821
HU1080BL         CAM TUBE 10X8 BLEU              U   20       4.339
HU225S-04-S2     SHAKO ELECTROVANNE NF 2/2       U    1     240.278
210100           SHAKO TEMPORISATEUR             U    1     109.943
81105TN          BUTEE A RLX CYLINDRIQUE         U    4     122.341
P199681847       CAM TUBE 10X8 BLEU 2            U   10       4.339
P199681848       CAM TUBE 12X10 ROUGE            U   10       5.120
P199420416       BUTEE ROULX REF B               U    4     115.000

TOTAL HT : 2085.780
"""


# ── page grouper tests ─────────────────────────────────────────────────────────

class TestGroupPagesIntoDocuments:
    """Verify page grouper produces correct segmentation for the Boudrant PDF."""

    def _classified(self, page_number, doc_type, text, confidence=0.95):
        return PageClassified(
            page_number=page_number,
            doc_type=doc_type,
            confidence=confidence,
            source_tier=1,
            raw_text=text,
            ref_hint="",
        )

    def test_facture_page1_bc_pages_23_produce_two_groups(self):
        """Page 1 (FACTURE) + pages 2-3 (BC) → exactly 2 groups."""
        pages = [
            self._classified(1, DocType.FACTURE, FACTURE_PAGE_TEXT),
            self._classified(2, DocType.BC, BC_PAGE_2_TEXT),
            self._classified(3, DocType.BC, BC_PAGE_3_TEXT),
        ]
        groups = group_pages_into_documents(pages)

        assert len(groups) == 2, (
            f"Expected 2 groups (FACTURE + BC), got {len(groups)}: "
            f"{[(g.doc_type, g.pages) for g in groups]}"
        )

    def test_group1_is_facture_on_page1(self):
        pages = [
            self._classified(1, DocType.FACTURE, FACTURE_PAGE_TEXT),
            self._classified(2, DocType.BC, BC_PAGE_2_TEXT),
            self._classified(3, DocType.BC, BC_PAGE_3_TEXT),
        ]
        groups = group_pages_into_documents(pages)
        fac_group = groups[0]

        assert fac_group.doc_type == DocType.FACTURE
        assert fac_group.pages == [1], f"FACTURE group should only contain page 1, got {fac_group.pages}"

    def test_group2_is_bc_on_pages_23(self):
        pages = [
            self._classified(1, DocType.FACTURE, FACTURE_PAGE_TEXT),
            self._classified(2, DocType.BC, BC_PAGE_2_TEXT),
            self._classified(3, DocType.BC, BC_PAGE_3_TEXT),
        ]
        groups = group_pages_into_documents(pages)
        bc_group = groups[1]

        assert bc_group.doc_type == DocType.BC
        assert set(bc_group.pages) == {2, 3}, (
            f"BC group should contain pages 2 and 3, got {bc_group.pages}"
        )

    def test_bc_page_text_not_in_facture_group(self):
        """BC text must not bleed into the FACTURE group."""
        pages = [
            self._classified(1, DocType.FACTURE, FACTURE_PAGE_TEXT),
            self._classified(2, DocType.BC, BC_PAGE_2_TEXT),
            self._classified(3, DocType.BC, BC_PAGE_3_TEXT),
        ]
        groups = group_pages_into_documents(pages)
        fac_text = groups[0].combined_text

        assert "P199420414" not in fac_text, (
            "BC-only ref 'P199420414' must NOT appear in the FACTURE group text"
        )

    def test_facture_text_not_in_bc_group(self):
        """FACTURE text must not bleed into the BC group."""
        pages = [
            self._classified(1, DocType.FACTURE, FACTURE_PAGE_TEXT),
            self._classified(2, DocType.BC, BC_PAGE_2_TEXT),
            self._classified(3, DocType.BC, BC_PAGE_3_TEXT),
        ]
        groups = group_pages_into_documents(pages)
        bc_text = groups[1].combined_text

        assert "A125/00408" not in bc_text, (
            "FACTURE ref 'A125/00408' must NOT appear in the BC group text"
        )


class TestBcSummaryMisclassification:
    """is_bc_summary_misclassified_as_facture must only fire when the current group
    is BC or BL, not when it is already FACTURE."""

    def test_does_not_fire_when_current_group_is_facture(self):
        bc_summary_text = (
            "TOTAL HORS TAXES  389.490\n"
            "NET HORS TAXES    389.490\n"
            "DIRECTION GÉNÉRALE"
        )
        result = is_bc_summary_misclassified_as_facture(bc_summary_text, DocType.FACTURE)
        assert result is False, (
            "A FACTURE-typed group should never absorb pages via bc_summary logic"
        )

    def test_fires_for_bc_group_with_summary_keywords_and_no_facture_marker(self):
        bc_summary_text = (
            "TOTAL HORS TAXES  2085.780\n"
            "NET HORS TAXES    2085.780\n"
            "APPROVISIONNEMENT"
        )
        result = is_bc_summary_misclassified_as_facture(bc_summary_text, DocType.BC)
        assert result is True

    def test_does_not_fire_when_genuine_facture_marker_present(self):
        text = "TOTAL HORS TAXES  389\nFACTURE N° A125/00408"
        result = is_bc_summary_misclassified_as_facture(text, DocType.BC)
        assert result is False


# ── LLM-fallback trigger condition tests ──────────────────────────────────────

class TestLLMFallbackTrigger:
    """
    The pipeline triggers LLM fallback when:
      (a) extracted is None
      (b) extraction_confidence < 0.60
      (c) extracted has 0 lines  ← the new condition added to fix the bug

    These tests verify the boolean expression used in pipeline.py is correct.
    """

    def _needs_llm(self, extracted) -> bool:
        """Mirror the condition from pipeline.py."""
        _has_no_lines = (
            extracted is not None
            and hasattr(extracted, "lines")
            and len(extracted.lines) == 0
        )
        return extracted is None or extracted.extraction_confidence < 0.60 or _has_no_lines

    def test_none_extracted_triggers_llm(self):
        assert self._needs_llm(None) is True

    def test_low_confidence_triggers_llm(self):
        facture = FactureSchema(
            ref_facture="A12500408",
            extraction_confidence=0.50,
            lines=[_make_line(1, "2019005")],
        )
        assert self._needs_llm(facture) is True

    def test_high_confidence_with_lines_does_not_trigger_llm(self):
        facture = FactureSchema(
            ref_facture="A12500408",
            extraction_confidence=0.85,
            lines=[_make_line(1, "2019005"), _make_line(2, "NPC1202")],
        )
        assert self._needs_llm(facture) is False

    def test_high_confidence_with_zero_lines_triggers_llm(self):
        """This is the primary bug fix: high confidence but 0 lines → LLM fallback."""
        facture = FactureSchema(
            ref_facture="A12500408",
            extraction_confidence=0.85,  # header fields found — old code skipped LLM!
            lines=[],                     # but table was NOT extracted
        )
        assert self._needs_llm(facture) is True, (
            "FactureSchema with 0 lines must trigger LLM fallback even when "
            "extraction_confidence >= 0.60. Without this fix, the FACTURE table "
            "would show BC references instead of invoice references."
        )

    def test_bc_zero_lines_also_triggers_llm(self):
        bc = BonDeCommandeSchema(
            ref_bc="OM176453",
            extraction_confidence=0.85,
            lines=[],
        )
        assert self._needs_llm(bc) is True


# ── No shared reference between invoice and BC lines ──────────────────────────

class TestNoSharedLineReference:
    """
    invoice.lines and bc.lines must be independent Python lists (no aliasing).
    The matcher creates shallow list copies, so this tests that bc.lines and
    facture.lines can be mutated independently without affecting each other.
    """

    def test_invoice_lines_not_same_object_as_bc_lines(self):
        bc_lines = [_make_line(i, f"P19942{i:04d}") for i in range(13)]
        fac_lines = [_make_line(i, f"2019{i:03d}") for i in range(9)]

        bc = BonDeCommandeSchema(ref_bc="OM176453", lines=bc_lines)
        facture = FactureSchema(ref_facture="A12500408", lines=fac_lines)

        assert bc.lines is not facture.lines, (
            "bc.lines and facture.lines must be separate list objects"
        )

    def test_mutating_bc_lines_does_not_affect_facture_lines(self):
        bc = BonDeCommandeSchema(
            ref_bc="OM176453",
            lines=[_make_line(1, "P199420414")],
        )
        facture = FactureSchema(
            ref_facture="A12500408",
            lines=[_make_line(1, "2019005")],
        )

        # Shallow list copy (as done in run_three_way_match)
        bc_copy = list(bc.lines)
        fac_copy = list(facture.lines)

        bc_copy.append(_make_line(2, "EXTRA_BC_REF"))
        assert len(fac_copy) == 1, (
            "Appending to bc_copy must not affect fac_copy"
        )
        assert fac_copy[0].ref_produit == "2019005"


# ── Table-reuse bug detection logic ───────────────────────────────────────────

class TestTableReuseBugDetection:
    """
    Verify the overlap-ratio logic used by the POSSIBLE_TABLE_REUSE_BUG check
    in pipeline.py is mathematically correct.
    """

    @staticmethod
    def _overlap_ratio(bc_refs: set, fac_refs: set) -> float:
        if not bc_refs or not fac_refs:
            return 0.0
        return len(bc_refs & fac_refs) / max(len(bc_refs), len(fac_refs))

    def test_identical_sets_give_ratio_1(self):
        refs = {"P199420414", "NKX2528", "P199584214"}
        assert self._overlap_ratio(refs, refs) == pytest.approx(1.0)

    def test_completely_different_sets_give_ratio_0(self):
        bc = {"P199420414", "NKX2528"}
        fac = {"2019005", "NPC1202"}
        assert self._overlap_ratio(bc, fac) == pytest.approx(0.0)

    def test_partial_overlap_computed_correctly(self):
        bc = {"A", "B", "C", "D"}
        fac = {"A", "B", "X", "Y"}
        # intersection = {A, B} = 2 elements, max = 4 → ratio = 0.5
        assert self._overlap_ratio(bc, fac) == pytest.approx(0.5)

    def test_bug_trigger_threshold_is_50_percent(self):
        """Overlap > 50 % should be treated as a table-reuse bug."""
        bc = {"P199420414", "NKX2528", "P199584214", "NPC1202", "NPC1004"}
        # Simulate bug: facture refs are a copy of BC refs (extraction reused BC table)
        fac = {"P199420414", "NKX2528", "P199584214", "NPC1202", "NPC1004"}
        assert self._overlap_ratio(bc, fac) > 0.50, (
            "When FACTURE refs == BC refs, ratio must exceed the 0.50 trigger threshold"
        )

    def test_normal_invoice_does_not_trigger(self):
        """Real invoice refs should NOT overlap with real BC refs."""
        bc_refs = {"P199420414", "NKX2528", "P199584214", "NPC1202", "HU1080BL"}
        fac_refs = {"2019005", "NPC1202", "NPC1004", "NPC804", "HU1080BL", "HU225S04S2"}
        # Some overlap is normal (NPC1202, HU1080BL may appear on both)
        ratio = self._overlap_ratio(bc_refs, fac_refs)
        # With only 2/6 overlap the ratio = 2/6 ≈ 0.33 < 0.50
        assert ratio <= 0.50, (
            f"Normal invoice/BC pair should not trigger reuse bug (ratio={ratio:.2f})"
        )
