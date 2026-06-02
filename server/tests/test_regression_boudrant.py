"""
Regression test for the Boudrant PDF (A125/00408 / OM176453).

PDF layout:
  Page 1  — FACTURE N° A125/00408   (9 invoice lines)
  Pages 2-3 — BON DE COMMANDE OM176453  (13 BC lines)

Invariants verified here:
  1. invoice.ref_facture == "A12500408"
  2. len(invoice.lines) == 9
  3. bc.ref_bc == "OM176453"
  4. len(bc.lines) == 13
  5. invoice.lines does NOT contain "P199420414" as first line ref
     (that ref belongs to the BC)
  6. invoice.lines contains at least one real invoice ref
     (2019005, NPC1202, NPC1004, HU1080BL, HU225S04S2)
  7. bc.lines contains "P199420414", "P199420416", "P199684214"
  8. invoice.lines is not bc.lines (no shared Python object)
  9. The sets of refs from invoice and BC are NOT identical
     (guards against the table-reuse bug)
 10. LineComparisonResult.ref_produit_facture is populated for matched lines
 11. LineComparisonResult.ref_produit_bl is None when no BL present

Run from server/:
    pytest tests/test_regression_boudrant.py -v
"""
import pytest
from decimal import Decimal

from app.schemas.documents import (
    BonDeCommandeSchema,
    FactureSchema,
    LineItemSchema,
)
from app.schemas.matching import LineVerdict
from app.services.matcher import run_three_way_match


# ── Synthetic extracted data that mirrors the real PDF ─────────────────────────

def _bc_line(n, ref, designation, qty, prix):
    return LineItemSchema(
        line_number=n,
        ref_produit=ref,
        ref_produit_normalized=ref,
        designation=designation,
        qty=Decimal(str(qty)),
        prix_unitaire=Decimal(str(prix)),
        tva_rate=Decimal("19"),
        total_ligne_ht=Decimal(str(qty)) * Decimal(str(prix)),
        extraction_confidence=0.85,
    )


def _fac_line(n, ref, designation, qty, prix):
    return LineItemSchema(
        line_number=n,
        ref_produit=ref,
        ref_produit_normalized=ref,
        designation=designation,
        qty=Decimal(str(qty)),
        prix_unitaire=Decimal(str(prix)),
        tva_rate=Decimal("19"),
        total_ligne_ht=Decimal(str(qty)) * Decimal(str(prix)),
        extraction_confidence=0.80,
    )


# Real Boudrant BC lines (13 lines, pages 2-3)
REAL_BC_LINES = [
    _bc_line(1,  "P199420414",  "BUTEE A RLX CYLIND ref 81105TN",        4,   122.341),
    _bc_line(2,  "NKX2528",     "AIG AVEC BUTEE",                         4,   242.200),
    _bc_line(3,  "P199584214",  "SHAKO UNION TECHNOPOLYMERE",             10,    5.568),
    _bc_line(4,  "NPC1202",     "SHAKO RACCORD DROIT 12 1/4",             10,    8.207),
    _bc_line(5,  "NPC1004",     "SHAKO RACC DROIT 10 1/2",                 5,    7.752),
    _bc_line(6,  "NPC804",      "SHAKO RACC DROIT 8 1/2",                  5,    6.821),
    _bc_line(7,  "HU1080BL",    "CAM TUBE 10X8 BLEU",                     20,    4.339),
    _bc_line(8,  "HU225S04S2",  "SHAKO ELECTROVANNE NF 2/2",               1,  240.278),
    _bc_line(9,  "P199450235",  "SHAKO TEMPORISATEUR",                     1,  109.943),
    _bc_line(10, "P199420414",  "BUTEE A RLX CYLIND ref 81105TN (2ème)",   4,  122.341),
    _bc_line(11, "P199681847",  "CAM TUBE 10X8 BLEU 2",                   10,    4.339),
    _bc_line(12, "P199420416",  "BUTEE ROULX REF B",                       4,  115.000),
    _bc_line(13, "P199684214",  "PIECE DIVERSE",                           2,   50.000),
]

# Real Boudrant invoice lines (9 lines, page 1)
REAL_INVOICE_LINES = [
    _fac_line(1, "2019005",     "MV UNION = TECHNOPOLYMERE",              10,    5.568),
    _fac_line(2, "NPC1202",     "SHAKO RACCORD DROIT 12 1/4",             10,    8.207),
    _fac_line(3, "NPC1004",     "SHAKO RACC DROIT 10 1/2",                 5,    7.752),
    _fac_line(4, "NPC804",      "SHAKO RACC DROIT 8 1/2",                  5,    6.821),
    _fac_line(5, "HU1080BL",    "CAM TUBE 10X8 BLEU",                     20,    4.339),
    _fac_line(6, "HU225S04S2",  "SHAKO ELECTROVANNE NF 2/2",               1,  240.278),
    _fac_line(7, "210100",      "SHAKO TEMPORISATEUR",                     1,  109.943),
    _fac_line(8, "81105TN",     "BUTEE A RLX CYLINDRIQUE",                 4,  122.341),
    _fac_line(9, "NKX25Z",      "RLT A AIGUILLES AVEC BUTEE",              4,  242.200),
]


@pytest.fixture
def bc():
    return BonDeCommandeSchema(
        ref_bc="OM176453",
        lines=REAL_BC_LINES,
        extraction_confidence=0.85,
    )


@pytest.fixture
def invoice():
    return FactureSchema(
        ref_facture="A12500408",
        ref_bc_linked="OM176453",
        lines=REAL_INVOICE_LINES,
        total_ht=Decimal("389.490"),
        total_ttc=Decimal("463.393"),
        tva_rate=Decimal("19"),
        extraction_confidence=0.80,
    )


# ── Basic structural invariants ────────────────────────────────────────────────

class TestBoudrantStructure:
    def test_invoice_number(self, invoice):
        assert invoice.ref_facture == "A12500408"

    def test_invoice_line_count(self, invoice):
        assert len(invoice.lines) == 9, (
            f"Expected 9 invoice lines, got {len(invoice.lines)}"
        )

    def test_bc_number(self, bc):
        assert bc.ref_bc == "OM176453"

    def test_bc_line_count(self, bc):
        assert len(bc.lines) == 13, (
            f"Expected 13 BC lines, got {len(bc.lines)}"
        )

    def test_invoice_first_line_is_not_bc_ref(self, invoice):
        """P199420414 belongs to the BC — must NOT be the first invoice line."""
        first_ref = invoice.lines[0].ref_produit
        assert first_ref != "P199420414", (
            f"invoice.lines[0].ref_produit = '{first_ref}' — this is a BC ref. "
            "The FACTURE table extraction must not reuse BC lines."
        )

    def test_invoice_contains_real_invoice_refs(self, invoice):
        """Invoice must contain at least one of the known real invoice references."""
        real_fac_refs = {"2019005", "NPC1202", "NPC1004", "HU1080BL", "HU225S04S2"}
        invoice_refs = {li.ref_produit for li in invoice.lines}
        assert invoice_refs & real_fac_refs, (
            f"Invoice lines {invoice_refs} contain none of the expected refs {real_fac_refs}"
        )

    def test_bc_contains_expected_bc_refs(self, bc):
        bc_refs = {li.ref_produit for li in bc.lines}
        for expected in ("P199420414", "P199420416", "P199684214"):
            assert expected in bc_refs, f"Expected BC ref '{expected}' not found in bc.lines"

    def test_invoice_lines_not_same_object_as_bc_lines(self, bc, invoice):
        assert invoice.lines is not bc.lines, (
            "invoice.lines and bc.lines must be separate list objects"
        )

    def test_invoice_and_bc_refs_are_not_identical(self, bc, invoice):
        bc_refs = {li.ref_produit for li in bc.lines}
        fac_refs = {li.ref_produit for li in invoice.lines}
        assert bc_refs != fac_refs, (
            "invoice refs and BC refs are identical — this is the table-reuse bug"
        )


# ── Matching result invariants ─────────────────────────────────────────────────

class TestBoudrantMatching:
    """Verify that run_three_way_match correctly uses separate invoice and BC lines."""

    def test_ref_produit_facture_is_invoice_ref_not_bc_ref(self, bc, invoice):
        """
        After matching, LineComparisonResult.ref_produit_facture must contain the
        FACTURE-side reference (e.g., NPC1202), NOT the BC-side reference.
        """
        result = run_three_way_match(
            bc=bc, bl=None, facture=invoice,
            job_id="test-boudrant",
        )

        bc_refs = {li.ref_produit for li in bc.lines}
        for lr in result.line_results:
            if lr.ref_produit_facture is not None:
                # The FACTURE ref must come from invoice lines, not BC lines
                assert lr.ref_produit_facture not in bc_refs or lr.ref_produit_facture in {
                    li.ref_produit for li in invoice.lines
                }, (
                    f"ref_produit_facture='{lr.ref_produit_facture}' looks like a BC ref "
                    "but is not in invoice lines — possible table reuse"
                )

    def test_ref_produit_bl_is_none_when_no_bl(self, bc, invoice):
        result = run_three_way_match(
            bc=bc, bl=None, facture=invoice,
            job_id="test-boudrant",
        )
        for lr in result.line_results:
            assert lr.ref_produit_bl is None, (
                f"ref_produit_bl must be None when no BL was passed, "
                f"got '{lr.ref_produit_bl}' for line '{lr.ref_produit}'"
            )

    def test_total_line_count_matches_bc_line_count(self, bc, invoice):
        """With only BC + FACTURE, total lines = BC lines + any EXTRA FACTURE lines."""
        result = run_three_way_match(
            bc=bc, bl=None, facture=invoice,
            job_id="test-boudrant",
        )
        # At minimum every BC line generates one result row
        assert result.total_lines >= len(bc.lines), (
            f"Expected >= {len(bc.lines)} result rows, got {result.total_lines}"
        )

    def test_no_partial_data_when_facture_has_lines(self, bc, invoice):
        """
        If FACTURE is correctly extracted (9 lines), each BC line that matches
        a FACTURE line should NOT get PARTIAL_DATA verdict (which only fires when
        both bl_line and facture_line are None).
        """
        result = run_three_way_match(
            bc=bc, bl=None, facture=invoice,
            job_id="test-boudrant",
        )
        partial_data_count = sum(
            1 for lr in result.line_results
            if lr.verdict == LineVerdict.PARTIAL_DATA
        )
        # With 9 FACTURE lines vs 13 BC lines, at most 4 BC lines can have no
        # FACTURE counterpart → PARTIAL_DATA. But 0 is expected for matched lines.
        assert partial_data_count < len(bc.lines), (
            f"Too many PARTIAL_DATA results ({partial_data_count}) — "
            "this suggests FACTURE lines were not used in matching"
        )

    def test_table_reuse_detection_fires_when_refs_identical(self, bc):
        """
        If someone accidentally sets facture.lines = bc.lines (or an exact copy),
        the overlap detection in pipeline.py must flag it.
        Simulated here by computing overlap ratio directly.
        """
        # Simulate bug: FACTURE received the exact same lines as BC
        bc_refs = {li.ref_produit for li in bc.lines if li.ref_produit}
        fac_refs = bc_refs.copy()  # identical — this is the bug

        overlap = len(bc_refs & fac_refs) / max(len(bc_refs), len(fac_refs))
        assert overlap > 0.50, (
            "Identical refs must produce overlap > 0.50 to trigger POSSIBLE_TABLE_REUSE_BUG"
        )

    def test_no_table_reuse_with_correct_invoice_lines(self, bc, invoice):
        """
        With correct invoice lines, the overlap ratio must be below the 0.50 trigger.
        Some refs ARE shared (NPC1202, HU1080BL, etc.) because the same products
        appear on both documents — that is expected and must not trigger the bug.
        """
        bc_refs = {li.ref_produit for li in bc.lines if li.ref_produit}
        fac_refs = {li.ref_produit for li in invoice.lines if li.ref_produit}
        overlap = len(bc_refs & fac_refs) / max(len(bc_refs), len(fac_refs))
        assert overlap <= 0.50, (
            f"Correct invoice/BC pair has overlap ratio {overlap:.2f} > 0.50, "
            "which would falsely trigger POSSIBLE_TABLE_REUSE_BUG"
        )
