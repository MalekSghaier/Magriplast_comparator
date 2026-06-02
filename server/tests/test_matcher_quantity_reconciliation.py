import asyncio
from decimal import Decimal

from app.schemas.documents import BonDeCommandeSchema, FactureSchema, LineItemSchema
from app.schemas.matching import LineVerdict
from app.services.matcher import MatchContext, match_line_item, run_three_way_match


def run(coro):
    return asyncio.run(coro)


def line(n, ref, designation, qty, price, total=None, tva="19"):
    return LineItemSchema(
        line_number=n,
        ref_produit=ref,
        ref_produit_normalized=ref,
        designation=designation,
        qty=Decimal(str(qty)) if qty is not None else None,
        prix_unitaire=Decimal(str(price)) if price is not None else None,
        total_ligne_ht=Decimal(str(total)) if total is not None else None,
        tva_rate=Decimal(str(tva)),
        extraction_confidence=0.90,
    )


def test_line_total_reconciles_obvious_invoice_qty_ocr_slip():
    ctx = MatchContext(job_id="qty-line-total")
    bc = line(1, "P199685061", "SHAKO ELECTROVANNE 2/2 1/4", 1, "240.278")
    facture = line(
        1,
        "AU2255-04-52",
        "SHAKO ELECTROVANNE NF 2/2 12",
        7,
        "24.028",
        total="240.278",
    )

    result = match_line_item(bc, None, facture, ctx, match_confidence=0.80)

    assert result.verdict == LineVerdict.MATCH
    assert result.mismatch_fields == []
    assert result.qty_facture == 1
    assert result.prix_facture == 240.278
    assert "line total" in result.notes


def test_math_consistent_invoice_qty_difference_stays_mismatch():
    ctx = MatchContext(job_id="qty-real-mismatch")
    bc = line(1, "P199685061", "SHAKO ELECTROVANNE 2/2 1/4", 1, "240.278")
    facture = line(
        1,
        "AU2255-04-52",
        "SHAKO ELECTROVANNE NF 2/2 12",
        7,
        "240.278",
        total="1681.946",
    )

    result = match_line_item(bc, None, facture, ctx, match_confidence=0.80)

    assert result.verdict == LineVerdict.MISMATCH
    assert result.mismatch_fields == ["qty_bc_vs_facture"]
    assert result.qty_facture == 7


def test_invoice_total_reconciles_multiple_missing_line_totals():
    bc = BonDeCommandeSchema(
        ref_bc="OM176453",
        lines=[
            line(1, "P199684214", "SHAKO UNION TECHNOPOLYMERE", 10, "5.568"),
            line(2, "P199685061", "SHAKO ELECTROVANNE 2/2 1/4", 1, "240.278"),
        ],
    )
    facture = FactureSchema(
        ref_facture="A12501085",
        ref_bc_linked="OM176453",
        total_ht=Decimal("295.958"),
        lines=[
            line(1, "P199684214", "SHAKO UNION TECHNOPOLYMERE", 9, "5.569"),
            line(2, "P199685061", "SHAKO ELECTROVANNE 2/2 1/4", 7, "24.028"),
        ],
    )

    result = run(run_three_way_match(bc=bc, bl=None, facture=facture, job_id="qty-doc-total"))

    assert result.mismatch_count == 0
    assert result.match_count == 2
    by_ref = {line_result.ref_produit: line_result for line_result in result.line_results}
    assert by_ref["P199684214"].qty_facture == 10
    assert by_ref["P199685061"].qty_facture == 1
    assert "invoice total" in by_ref["P199685061"].notes


def test_invoice_total_does_not_reconcile_when_extracted_values_match_total():
    bc = BonDeCommandeSchema(
        ref_bc="OM176453",
        lines=[
            line(1, "P199684214", "SHAKO UNION TECHNOPOLYMERE", 10, "5.568"),
            line(2, "P199685061", "SHAKO ELECTROVANNE 2/2 1/4", 1, "240.278"),
        ],
    )
    facture = FactureSchema(
        ref_facture="A12501085",
        ref_bc_linked="OM176453",
        total_ht=Decimal("1732.067"),
        lines=[
            line(1, "P199684214", "SHAKO UNION TECHNOPOLYMERE", 9, "5.569"),
            line(2, "P199685061", "SHAKO ELECTROVANNE 2/2 1/4", 7, "240.278"),
        ],
    )

    result = run(run_three_way_match(bc=bc, bl=None, facture=facture, job_id="qty-real-total"))

    assert result.mismatch_count == 2
    assert all(
        line_result.mismatch_fields == ["qty_bc_vs_facture"]
        for line_result in result.line_results
    )


def test_likely_bc_tva_ocr_slip_uses_facture_tva_consensus():
    ctx = MatchContext(job_id="tva-ocr")
    bc = line(1, "P199450265", "SHAKO RACC DROIT 12-14", 10, "6.207", tva="15")
    facture = line(1, "NPC12-02", "SHAKO RACCORD DROIT 12 1/4", 10, "6.207", tva="19")

    result = match_line_item(
        bc,
        None,
        facture,
        ctx,
        match_confidence=0.80,
        trusted_facture_tva_rate=Decimal("19"),
    )

    assert result.verdict == LineVerdict.MATCH
    assert result.mismatch_fields == []
    assert result.tva_bc == 19
    assert result.tva_facture == 19
    assert "TVA reconciled" in result.notes


def test_real_tva_difference_stays_mismatch():
    ctx = MatchContext(job_id="tva-real")
    bc = line(1, "P199450265", "SHAKO RACC DROIT 12-14", 10, "6.207", tva="13")
    facture = line(1, "NPC12-02", "SHAKO RACCORD DROIT 12 1/4", 10, "6.207", tva="19")

    result = match_line_item(
        bc,
        None,
        facture,
        ctx,
        match_confidence=0.80,
        trusted_facture_tva_rate=Decimal("19"),
    )

    assert result.verdict == LineVerdict.MISMATCH
    assert result.mismatch_fields == ["tva_rate"]
    assert result.tva_bc == 13
    assert result.tva_facture == 19
