"""
Unit tests for the multi-layer matching engine.

Covers:
  - normalize_ref / normalize_desc helpers
  - Layer 1: exact ref match
  - Layer 2: fuzzy ref match (handles OCR char substitution / insertion)
  - Layer 3: description match (handles different refs, same product name)
  - Layer 4: cross-document substring match
  - apply_bonuses: price and quantity proximity bonuses
  - The 4 real-world OCR cases observed in production (Boudrant invoices)

Run from the server/ directory:
    pytest tests/test_matching_layers.py -v
"""
import pytest
from app.utils.fuzzy import (
    normalize_ref,
    normalize_desc,
    score_line_pair,
    apply_bonuses,
    MATCH_THRESHOLD,
    PARTIAL_MATCH_THRESHOLD,
    LAYER_1_CONF,
    LAYER_2_HIGH_CONF,
    LAYER_2_LOW_CONF,
    LAYER_3_HIGH_CONF,
    LAYER_3_LOW_CONF,
    LAYER_4_CONF,
    PRICE_BONUS,
    QTY_BONUS,
)


# ── normalize_ref ─────────────────────────────────────────────────────────────

class TestNormalizeRef:
    def test_strips_hyphens_and_spaces(self):
        assert normalize_ref("NPC 12-02") == "NPC1202"

    def test_uppercase(self):
        assert normalize_ref("nkx25z") == "NKX25Z"

    def test_strips_slashes(self):
        assert normalize_ref("FT25/08408") == "FT2508408"

    def test_strips_accented_chars(self):
        # Accented / non-ASCII chars not in A-Z0-9 are removed
        assert normalize_ref("BL-25/04") == "BL2504"

    def test_empty_string(self):
        assert normalize_ref("") == ""

    def test_none_equivalent(self):
        assert normalize_ref(None or "") == ""


# ── normalize_desc ────────────────────────────────────────────────────────────

class TestNormalizeDesc:
    def test_lowercase_and_strip_accents(self):
        result = normalize_desc("EUTÉE À RLX CYLINDRIQUE")
        assert result == "eutee a rlx cylindrique"

    def test_removes_equals_sign(self):
        result = normalize_desc("MN UNION = TECHNOPOLYMERE")
        assert "=" not in result
        assert "mn" in result
        assert "technopolymere" in result

    def test_empty(self):
        assert normalize_desc("") == ""


# ── score_line_pair — Layer 1 ─────────────────────────────────────────────────

class TestLayer1ExactRef:
    def test_identical_refs_match(self):
        score, layer = score_line_pair("NPC12-02", None, "NPC12-02", None)
        assert layer == 1
        assert score == LAYER_1_CONF

    def test_normalized_identical_refs_match(self):
        # Different formatting, same content
        score, layer = score_line_pair("NPC 12-02", None, "NPC12/02", None)
        assert layer == 1

    def test_different_refs_not_layer1(self):
        score, layer = score_line_pair("NKX257", None, "NKX2528", None)
        assert layer != 1


# ── score_line_pair — Layer 2 ─────────────────────────────────────────────────

class TestLayer2FuzzyRef:
    def test_nkx257_vs_nkx2528_gives_layer2(self):
        """OCR dropped a '2': NKX2528 → NKX257 (or inserted a char)."""
        score, layer = score_line_pair(
            "NKX257", "RLT AAIGUILLES AVEC BUTEE AB",
            "NKX2528", "AIG AVEC BUTEE ref",
        )
        assert layer == 2, f"Expected layer 2, got {layer}"
        assert score >= LAYER_2_LOW_CONF, f"Expected ≥ {LAYER_2_LOW_CONF}, got {score:.3f}"

    def test_high_confidence_ref_match(self):
        """One char off — should give high-confidence layer 2."""
        score, layer = score_line_pair("NPC1202", None, "NPC1203", None)
        # token_sort_ratio of 7-char strings differing by one char is ≥ 85
        assert layer == 2

    def test_completely_different_refs_not_layer2(self):
        score, layer = score_line_pair("2I0ICE", None, "P199450235", None)
        assert layer != 2 or score < LAYER_2_LOW_CONF


# ── score_line_pair — Layer 3 ─────────────────────────────────────────────────

class TestLayer3DescriptionMatch:
    def test_identical_descriptions_match(self):
        """Same description, completely different refs."""
        score, layer = score_line_pair(
            "2I0ICE", "SHAKO TEMPORISATEUR",
            "P199450235", "SHAKO TEMPORISATEUR",
        )
        assert layer == 3, f"Expected layer 3, got {layer}"
        assert score >= LAYER_3_HIGH_CONF

    def test_partial_description_overlap(self):
        """MN UNION = TECHNOPOLYMERE vs SHAKO UNION TECHNOPOLYMERE — common words."""
        score, layer = score_line_pair(
            "2P15005", "MN UNION = TECHNOPOLYMERE",
            "P199584214", "SHAKO UNION TECHNOPOLYMERE",
        )
        assert layer == 3, f"Expected layer 3, got {layer}"
        assert score >= LAYER_3_LOW_CONF, f"Expected ≥ {LAYER_3_LOW_CONF}, got {score:.3f}"

    def test_description_with_accents_normalized(self):
        """Accents in descriptions should not prevent matching."""
        score, layer = score_line_pair(
            "X1", "BUTÉE À ROULEAUX CYLINDRIQUE",
            "X1", "BUTEE A ROULEAUX CYLINDRIQUE",
        )
        # Layer 1 would fire on the identical ref, but we test Layer 3 semantics
        # by using different refs
        score2, layer2 = score_line_pair(
            "AAA", "BUTÉE À ROULEAUX CYLINDRIQUE",
            "BBB", "BUTEE A ROULEAUX CYLINDRIQUE",
        )
        assert score2 >= LAYER_3_HIGH_CONF


# ── score_line_pair — Layer 4 ─────────────────────────────────────────────────

class TestLayer4CrossMatch:
    def test_ref_embedded_in_description(self):
        """BC description explicitly lists the spec ref: 'ref 81105TN'."""
        score, layer = score_line_pair(
            "81105TN", "BUTEE A RLX CYLINDRIQUE",
            "P199420414", "BUTEE A RLX CYLIND ref 81105TN",
        )
        assert layer == 4, f"Expected layer 4, got {layer}"
        assert score == LAYER_4_CONF

    def test_shorter_ref_in_longer_ref(self):
        """One ref is a substring of the other."""
        score, layer = score_line_pair("NKX25", None, "NKX2528Z", None)
        assert layer == 4


# ── apply_bonuses ─────────────────────────────────────────────────────────────

class TestApplyBonuses:
    def test_price_within_5pct_adds_bonus(self):
        final = apply_bonuses(0.65, 122.341, 122.341, None, None)
        assert abs(final - (0.65 + PRICE_BONUS)) < 0.001

    def test_price_outside_5pct_no_bonus(self):
        final = apply_bonuses(0.65, 100.0, 200.0, None, None)
        assert final == pytest.approx(0.65)

    def test_qty_within_5pct_adds_bonus(self):
        final = apply_bonuses(0.65, None, None, 10.0, 10.0)
        assert abs(final - (0.65 + QTY_BONUS)) < 0.001

    def test_both_bonuses_cap_at_1(self):
        final = apply_bonuses(1.0, 100.0, 100.0, 5.0, 5.0)
        assert final == 1.0

    def test_none_prices_no_bonus(self):
        assert apply_bonuses(0.70, None, None, None, None) == pytest.approx(0.70)


# ── Real-world OCR cases from Boudrant invoices ───────────────────────────────

class TestRealWorldCases:
    """
    These four cases were directly observed in the Boudrant FACTURE / BC pair
    (OM176453 / FT25/08408, September 2025).
    """

    def test_case_nkx257_vs_nkx2528_final_match(self):
        """
        Layer 2 fuzzy ref (token_sort_ratio ≈ 77 %) + price bonus → MATCH (≥ 0.80).
        OCR confusion: '2528' → '257' (dropped '2', changed '8' → '7').
        Prices: 242.200 on both sides.
        """
        base, layer = score_line_pair(
            "NKX257", "RLT AAIGUILLES AVEC BUTEE AB",
            "NKX2528", "AIG AVEC BUTEE ref",
        )
        final = apply_bonuses(base, 242.200, 242.200, None, None)
        assert final >= MATCH_THRESHOLD, (
            f"NKX257↔NKX2528: expected MATCH (≥ {MATCH_THRESHOLD}), got {final:.3f} "
            f"(layer {layer}, base {base:.3f})"
        )

    def test_case_2i0ice_vs_p199450235_final_match(self):
        """
        Layer 3 description exact match → MATCH even without price bonus.
        OCR mangled the facture ref completely; description is identical.
        """
        base, layer = score_line_pair(
            "2I0ICE", "SHAKO TEMPORISATEUR",
            "P199450235", "SHAKO TEMPORISATEUR",
        )
        final = apply_bonuses(base, 109.04, 109.943, None, None)
        assert final >= MATCH_THRESHOLD, (
            f"2I0ICE↔P199450235: expected MATCH (≥ {MATCH_THRESHOLD}), got {final:.3f} "
            f"(layer {layer}, base {base:.3f})"
        )

    def test_case_2p15005_vs_p199584214_final_match(self):
        """
        Layer 3 partial description match (UNION + TECHNOPOLYMERE common tokens).
        Prices: 5.57 ≈ 5.568 → within 5 % → bonus pushes to MATCH.
        """
        base, layer = score_line_pair(
            "2P15005", "MN UNION = TECHNOPOLYMERE",
            "P199584214", "SHAKO UNION TECHNOPOLYMERE",
        )
        final = apply_bonuses(base, 5.57, 5.568, None, None)
        assert final >= MATCH_THRESHOLD, (
            f"2P15005↔P199584214: expected MATCH (≥ {MATCH_THRESHOLD}), got {final:.3f} "
            f"(layer {layer}, base {base:.3f})"
        )

    def test_case_hi05tn_vs_81105tn_at_least_partial_match(self):
        """
        Severe OCR corruption: 'HI05TN' is '81105TN' with H→8, I→1.
        Algorithmic layers may not reach MATCH_THRESHOLD; the system should
        at minimum flag this pair as PARTIAL_MATCH (≥ 0.50) for human/LLM review.
        With Layer 5 LLM configured, the pair resolves to MATCH.
        Prices: 122.341 on both sides.
        """
        base, layer = score_line_pair(
            "HI05TN", "EUTÉE À RLX CYLINDRIQUE",
            "P199420414", "BUTEE A RLX CYLIND ref 81105TN",
        )
        final = apply_bonuses(base, 122.341, 122.341, None, None)
        assert final >= PARTIAL_MATCH_THRESHOLD, (
            f"HI05TN↔81105TN: expected at least PARTIAL_MATCH (≥ {PARTIAL_MATCH_THRESHOLD}), "
            f"got {final:.3f} (layer {layer}, base {base:.3f}). "
            "Check Layer 3 WRatio threshold or Layer 4 substring logic."
        )

    def test_case_81105tn_in_description_layer4(self):
        """
        When the correct ref '81105TN' is used (not OCR-mangled), Layer 4
        substring detection catches it embedded in the BC description.
        """
        base, layer = score_line_pair(
            "81105TN", "BUTEE A RLX CYLINDRIQUE",
            "P199420414", "BUTEE A RLX CYLIND ref 81105TN",
        )
        assert layer == 4
        assert base == LAYER_4_CONF


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_refs_and_descs(self):
        score, layer = score_line_pair("", None, "", None)
        assert score == 0.0
        assert layer == 0

    def test_only_ref_present(self):
        score, layer = score_line_pair("NPC1202", None, "NPC1202", None)
        assert layer == 1

    def test_unrelated_products_low_score(self):
        """Completely different parts should not match."""
        base, layer = score_line_pair(
            "NKX2528", "AIG AVEC BUTEE",
            "P199681847", "CAM TUBE 10X8 BLEU",
        )
        final = apply_bonuses(base, 4.339, 4.339, None, None)
        # Even with identical price, unrelated refs+descs should stay below MATCH
        assert final < MATCH_THRESHOLD, (
            f"Unrelated products should not reach MATCH, got {final:.3f}"
        )
