import asyncio
from decimal import Decimal

from app.schemas.documents import BonDeCommandeSchema, FactureSchema, LineItemSchema
from app.schemas.matching import LineVerdict
from app.services.matcher import run_three_way_match
from app.services.reference_aliases import ReferenceAlias


def run(coro):
    return asyncio.run(coro)


def line(n, ref, designation, qty, price, extraction_confidence=0.90):
    return LineItemSchema(
        line_number=n,
        ref_produit=ref,
        ref_produit_normalized=ref,
        designation=designation,
        qty=Decimal(str(qty)),
        prix_unitaire=Decimal(str(price)),
        total_ligne_ht=Decimal(str(qty)) * Decimal(str(price)),
        tva_rate=Decimal("19"),
        extraction_confidence=extraction_confidence,
    )


def alias(external_ref, internal_ref):
    return ReferenceAlias(
        id="alias-1",
        supplier_key="name:BOUDRANT",
        supplier_name="BOUDRANT",
        external_ref=external_ref,
        external_ref_normalized=external_ref,
        internal_ref=internal_ref,
        internal_ref_normalized=internal_ref,
    )


def test_reference_alias_promotes_supplier_code_to_match():
    bc = BonDeCommandeSchema(
        ref_bc="OM176453",
        lines=[
            line(1, "P199420414", "BUTEE A RLX CYLIND ref 81105TN", 4, "122.341"),
        ],
    )
    facture = FactureSchema(
        ref_facture="FT2508408",
        ref_bc_linked="OM176453",
        supplier_name="BOUDRANT",
        lines=[
            line(1, "81105TN", "BUTEE A RLX CYLINDRIQUE", 4, "122.341"),
        ],
    )

    result = run(run_three_way_match(
        bc=bc,
        bl=None,
        facture=facture,
        job_id="alias-match",
        reference_aliases={"81105TN": alias("81105TN", "P199420414")},
    ))

    assert result.match_count == 1
    assert result.low_confidence_count == 0
    matched = result.line_results[0]
    assert matched.verdict == LineVerdict.MATCH
    assert matched.match_layer == 6
    assert matched.reference_alias_applied is True
    assert matched.reference_alias_external == "81105TN"
    assert matched.reference_alias_internal == "P199420414"
    assert matched.confidence >= 0.80


def test_reference_alias_resolves_low_ref_extraction_confidence():
    bc = BonDeCommandeSchema(
        ref_bc="OM176453",
        lines=[
            line(1, "P199420416", "RLT A AIG AVEC BUTEE ref NKX 25Z", 4, "242.200"),
        ],
    )
    facture = FactureSchema(
        ref_facture="FT2508408",
        ref_bc_linked="OM176453",
        supplier_name="BOUDRANT",
        lines=[
            line(
                1,
                "NKX252",
                "RLT A AIGUILLES AVEC BUTEE A B",
                4,
                "242.200",
                extraction_confidence=0.40,
            ),
        ],
    )

    result = run(run_three_way_match(
        bc=bc,
        bl=None,
        facture=facture,
        job_id="alias-low-ref-confidence",
        reference_aliases={"NKX252": alias("NKX252", "P199420416")},
    ))

    matched = result.line_results[0]
    assert result.match_count == 1
    assert result.low_confidence_count == 0
    assert matched.verdict == LineVerdict.MATCH
    assert matched.match_layer == 6
    assert matched.reference_alias_applied is True
    assert matched.confidence >= 0.80


def test_reference_alias_does_not_hide_field_mismatch():
    bc = BonDeCommandeSchema(
        ref_bc="OM176453",
        lines=[
            line(1, "P199420414", "BUTEE A RLX CYLIND ref 81105TN", 4, "122.341"),
        ],
    )
    facture = FactureSchema(
        ref_facture="FT2508408",
        ref_bc_linked="OM176453",
        supplier_name="BOUDRANT",
        lines=[
            line(1, "81105TN", "BUTEE A RLX CYLINDRIQUE", 5, "122.341"),
        ],
    )

    result = run(run_three_way_match(
        bc=bc,
        bl=None,
        facture=facture,
        job_id="alias-mismatch",
        reference_aliases={"81105TN": alias("81105TN", "P199420414")},
    ))

    matched = result.line_results[0]
    assert result.mismatch_count == 1
    assert matched.verdict == LineVerdict.MISMATCH
    assert matched.match_layer == 6
    assert matched.reference_alias_applied is True
    assert matched.mismatch_fields == ["qty_bc_vs_facture"]
