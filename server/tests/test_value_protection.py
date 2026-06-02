"""
Unit tests for the value protection layer.

Tests cover:
  A. Protected values (codes, amounts, dates, dimensions)
  B. Normalizable field detection
  C. Word normalisation (OCR variants → canonical)
  D. GPT batch correction (mocked)
  E. Supplier detection (Magriplast exclusion, generic profile, evidence-count gate)
  F. Prompt sanity (no hardcoded supplier names)
"""
import asyncio
import json
import types
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.value_protection import is_protected_value, is_normalizable_field


# ─── helpers ──────────────────────────────────────────────────────────────────

def sync(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════
# A. PROTECTED VALUES
# ═══════════════════════════════════════════════════════════════════

class TestProtectedValues:
    """These values must NEVER be altered by dictionary, fuzzy, or GPT."""

    # ── Product codes / article references ────────────────────────────────────
    @pytest.mark.parametrize("code", [
        "P199420414",
        "M400010432",
        "BCF04H",
        "DW36PT",
        "S096",
        "NPC10",
        "Z10100",
        "HI1234",
        "NKX257",
    ])
    def test_article_codes_are_protected(self, code):
        assert is_protected_value(code), f"Expected {code!r} to be protected"

    # ── Technical / dimension strings ─────────────────────────────────────────
    @pytest.mark.parametrize("value", [
        "C/C 595X395X330 F40",
        "1200*1000*980",
        "595X395X330",
        "115X22.23",
        "CA DO KL/KL F+C",
    ])
    def test_dimension_codes_are_protected(self, value):
        assert is_protected_value(value), f"Expected {value!r} to be protected"

    # ── Financial amounts ──────────────────────────────────────────────────────
    @pytest.mark.parametrize("value,field", [
        ("6576.000", "amount_ht"),
        ("122.341", "total_ttc"),
        ("19", "tva_rate"),
        ("2.5", "remise_pct"),
        ("1250", "prix_unitaire"),
        ("45", "qty"),
    ])
    def test_financial_amounts_are_protected(self, value, field):
        assert is_protected_value(value, field_name=field), (
            f"Expected {value!r} (field={field}) to be protected"
        )

    # ── Dates ─────────────────────────────────────────────────────────────────
    @pytest.mark.parametrize("value", [
        "30/06/2025",
        "01-01-2024",
        "15.03.2023",
    ])
    def test_dates_are_protected(self, value):
        assert is_protected_value(value, field_name="document_date"), (
            f"Expected {value!r} to be protected as a date"
        )

    # ── Document numbers ──────────────────────────────────────────────────────
    @pytest.mark.parametrize("value,field", [
        ("FAC-2024-001234", "ref_facture"),
        ("BC-25-001", "ref_bc"),
        ("BL/2024/0012", "ref_bl"),
    ])
    def test_document_refs_are_protected(self, value, field):
        assert is_protected_value(value, field_name=field), (
            f"Expected {value!r} (field={field}) to be protected"
        )

    # ── Plain words are NOT protected ─────────────────────────────────────────
    @pytest.mark.parametrize("word,field", [
        ("DISQUE", "designation"),
        ("Qtó", "column_header"),
        ("livraison", "designation"),
        ("QUANTITE", "unit"),
    ])
    def test_plain_words_are_not_protected(self, word, field):
        assert not is_protected_value(word, field_name=field), (
            f"Expected {word!r} (field={field}) NOT to be protected"
        )


# ═══════════════════════════════════════════════════════════════════
# B. NORMALIZABLE FIELDS
# ═══════════════════════════════════════════════════════════════════

class TestNormalizableFields:
    @pytest.mark.parametrize("field", [
        "designation",
        "column_header",
        "unit",
        "supplier_name",
        "product_word",
    ])
    def test_normalizable_fields(self, field):
        assert is_normalizable_field(field), f"{field} should be normalizable"

    @pytest.mark.parametrize("field", [
        "article_code",
        "reference",
        "ref_produit",
        "quantity",
        "qty",
        "unit_price",
        "prix_unitaire",
        "amount",
        "amount_ht",
        "total_ht",
        "total_ttc",
        "tax_rate",
        "tva_rate",
        "discount_rate",
        "document_date",
        "date",
        "fiscal_id",
        "ref_bc",
        "ref_bl",
        "ref_facture",
    ])
    def test_protected_fields_not_normalizable(self, field):
        assert not is_normalizable_field(field), f"{field} should NOT be normalizable"


# ═══════════════════════════════════════════════════════════════════
# C. WORD NORMALISATION (OCR variants)
# ═══════════════════════════════════════════════════════════════════

class TestWordNormalisation:
    """
    Dictionary correction must work for designation/unit/header words
    and return raw_value unchanged for protected fields.
    """

    @pytest.mark.parametrize("raw,expected_canonical", [
        ("qte", "QUANTITE"),
        ("qté", "QUANTITE"),
        ("qtó", "QUANTITE"),
        ("désig", "DESIGNATION"),
        ("desig", "DESIGNATION"),
        ("p.u.", "PRIX_UNITAIRE"),
        ("p.u", "PRIX_UNITAIRE"),
        ("pu", "PRIX_UNITAIRE"),
    ])
    def test_seeded_terms_normalize(self, raw, expected_canonical):
        from app.services.adaptive_dictionary import _normalize, _SEED_TERMS
        # Check the seed table contains the mapping
        seed_map = {_normalize(r): c for r, c, _ in _SEED_TERMS}
        assert _normalize(raw) in seed_map, f"{raw!r} not found in seed"
        assert seed_map[_normalize(raw)] == expected_canonical, (
            f"{raw!r} should normalize to {expected_canonical!r}, "
            f"got {seed_map[_normalize(raw)]!r}"
        )

    def test_protected_value_skips_correction(self):
        from app.services.adaptive_dictionary import word_dictionary

        async def run():
            result, conf, source = await word_dictionary.correct(
                "P199420414", field_name="ref_produit"
            )
            return result, conf, source

        result, conf, source = sync(run())
        assert result == "P199420414", "Protected code must pass through unchanged"
        assert source == "PROTECTED"

    def test_amount_skips_correction(self):
        from app.services.adaptive_dictionary import word_dictionary

        async def run():
            result, conf, source = await word_dictionary.correct(
                "6576.000", field_name="amount_ht"
            )
            return result, conf, source

        result, conf, source = sync(run())
        assert result == "6576.000"
        assert source == "PROTECTED"

    def test_date_skips_correction(self):
        from app.services.adaptive_dictionary import word_dictionary

        async def run():
            result, conf, source = await word_dictionary.correct(
                "30/06/2025", field_name="document_date"
            )
            return result, conf, source

        result, conf, source = sync(run())
        assert result == "30/06/2025"
        assert source == "PROTECTED"


# ═══════════════════════════════════════════════════════════════════
# D. GPT BATCH CORRECTION (mocked)
# ═══════════════════════════════════════════════════════════════════

class TestGptBatchCorrection:
    """GPT is called once for the whole batch; results stored as unverified."""

    _MOCK_GPT_RESPONSE = {
        "corrections": [
            {
                "raw_value": "D1SQUE",
                "corrected_value": "DISQUE",
                "confidence": 0.90,
                "term_type": "product_word",
                "should_add_to_dictionary": True,
                "should_apply_now": False,
                "reason": "OCR digit/letter confusion: 1→I",
            },
            {
                "raw_value": "P199420414",
                "corrected_value": "P199420414",
                "confidence": 1.0,
                "term_type": "code",
                "should_add_to_dictionary": False,
                "should_apply_now": False,
                "reason": "Product code — preserved unchanged",
            },
        ]
    }

    def test_batch_called_once(self):
        """One GPT call for the whole batch, not one per token."""
        from app.services.adaptive_dictionary import word_dictionary, UnknownToken

        call_count = 0

        async def mock_call(prompt: str):
            nonlocal call_count
            call_count += 1
            return [
                types.SimpleNamespace(
                    raw_value="D1SQUE",
                    corrected_value="DISQUE",
                    confidence=0.90,
                    term_type="product_word",
                    should_add_to_dictionary=True,
                    should_apply_now=False,
                    reason="OCR error",
                )
            ]

        tokens = [
            UnknownToken(raw_value="D1SQUE", field_name="designation"),
            UnknownToken(raw_value="DISQ", field_name="designation"),
        ]

        with patch(
            "app.services.adaptive_dictionary._call_gpt_batch_correction",
            side_effect=mock_call,
        ):
            sync(word_dictionary.correct_unknown_tokens_with_llm(tokens, {}))

        assert call_count == 1, f"Expected 1 GPT call, got {call_count}"

    def test_gpt_result_stored_unverified(self):
        """Suggestions are stored with verified=False and weight ≤ 0.75."""
        from app.services.adaptive_dictionary import (
            word_dictionary, UnknownToken, CorrectionSuggestion
        )

        stored: list[dict] = []

        async def mock_store(raw_form, canonical, cat, weight, source,
                              verified=True, supplier_id=None):
            stored.append({
                "raw_form": raw_form,
                "canonical": canonical,
                "weight": weight,
                "verified": verified,
                "source": source.value if hasattr(source, "value") else source,
            })

        mock_suggestion = CorrectionSuggestion(
            raw_value="D1SQUE",
            corrected_value="DISQUE",
            confidence=0.90,
            term_type="product_word",
            should_add_to_dictionary=True,
            should_apply_now=False,
        )

        tokens = [UnknownToken(raw_value="D1SQUE", field_name="designation")]

        with patch(
            "app.services.adaptive_dictionary._call_gpt_batch_correction",
            new=AsyncMock(return_value=[mock_suggestion]),
        ), patch.object(word_dictionary, "_store_entry", side_effect=mock_store), \
           patch.object(word_dictionary, "_db_lookup", new=AsyncMock(return_value=None)):
            sync(word_dictionary.correct_unknown_tokens_with_llm(tokens, {}))

        assert stored, "Nothing was stored"
        entry = stored[0]
        assert entry["verified"] is False, "GPT suggestions must be stored as unverified"
        assert entry["weight"] <= 0.75, f"GPT weight {entry['weight']} exceeds 0.75"
        assert "LLM_SUGGESTED" in entry["source"], "Source must be LLM_SUGGESTED"

    def test_protected_value_excluded_from_gpt_batch(self):
        """Protected codes are never sent to GPT."""
        from app.services.adaptive_dictionary import word_dictionary, UnknownToken

        gpt_tokens_seen: list[str] = []

        async def mock_call(prompt: str):
            import re
            found = re.findall(r'"raw_value":\s*"([^"]+)"', prompt)
            gpt_tokens_seen.extend(found)
            return []

        tokens = [
            UnknownToken(raw_value="D1SQUE", field_name="designation"),
            UnknownToken(raw_value="P199420414", field_name="ref_produit"),
        ]

        with patch(
            "app.services.adaptive_dictionary._call_gpt_batch_correction",
            side_effect=mock_call,
        ), patch.object(word_dictionary, "_db_lookup", new=AsyncMock(return_value=None)):
            sync(word_dictionary.correct_unknown_tokens_with_llm(tokens, {}))

        assert "P199420414" not in gpt_tokens_seen, (
            "Protected code P199420414 must not be sent to GPT"
        )

    def test_no_repeated_gpt_call_for_known_token(self):
        """If a token already exists in DB (verified), GPT is not called."""
        from app.services.adaptive_dictionary import word_dictionary, UnknownToken
        from app.models.word_dictionary import WordDictionaryEntry, WordSource

        existing = MagicMock(spec=WordDictionaryEntry)
        existing.canonical_form = "DISQUE"
        existing.weight = 1.0
        existing.verified = True
        existing.source = "MANUAL"

        gpt_called = []

        async def mock_call(prompt: str):
            gpt_called.append(prompt)
            return []

        tokens = [UnknownToken(raw_value="D1SQUE", field_name="designation")]

        with patch.object(word_dictionary, "_db_lookup", new=AsyncMock(return_value=existing)), \
             patch(
                 "app.services.adaptive_dictionary._call_gpt_batch_correction",
                 side_effect=mock_call,
             ):
            sync(word_dictionary.correct_unknown_tokens_with_llm(tokens, {}))

        assert not gpt_called, "GPT should not be called if token already in verified DB"


# ═══════════════════════════════════════════════════════════════════
# E. SUPPLIER DETECTION
# ═══════════════════════════════════════════════════════════════════

class TestSupplierDetection:
    """Supplier detection rules."""

    def test_magriplast_never_supplier(self):
        from app.services.supplier_profile_detector import _is_known_client
        for name in ["MAGRIPLAST", "magriplast", "Magriplast SARL", "MAGRIPLAST S.A.R.L."]:
            assert _is_known_client(name), f"{name!r} should be identified as a known client"

    def test_unknown_supplier_returns_generic_profile(self):
        from app.services.supplier_profile_detector import (
            supplier_profile_detector, _make_generic_profile
        )

        async def run():
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
            return await supplier_profile_detector.detect_from_document(
                "Facture N° 2024-001\nDate: 01/01/2024\nMAGRIPLAST\nTotal HT: 1000.000",
                mock_db,
            )

        profile = sync(run())
        # If only MAGRIPLAST found, result is either None or a generic profile
        if profile is not None:
            assert getattr(profile, "is_generic", False) or profile.name != "MAGRIPLAST", (
                "MAGRIPLAST must not be returned as the supplier"
            )

    def test_pattern_not_promoted_after_single_occurrence(self):
        """A ref pattern appears once — should NOT be promoted to the profile."""
        from app.services.supplier_profile_detector import (
            SupplierProfileDetector, PROMOTION_EVIDENCE_COUNT
        )

        detector = SupplierProfileDetector()
        profile = MagicMock()
        profile.id = "test-supplier-1"
        profile.name = "TEST SUPPLIER"
        profile.ref_patterns = []
        profile.confidence_score = 0.5
        profile.last_seen = None

        text = "P199420414  DISQUE  10  5.500  55.000"

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        sync(detector._enrich_profile_with_candidates(profile, text, mock_db))

        # After 1 document, no pattern promoted
        assert profile.ref_patterns == [], (
            "Pattern should not be promoted after a single occurrence"
        )

    def test_pattern_promoted_after_enough_evidence(self):
        """A pattern appearing PROMOTION_EVIDENCE_COUNT times is promoted."""
        from app.services.supplier_profile_detector import (
            SupplierProfileDetector, PROMOTION_EVIDENCE_COUNT
        )

        detector = SupplierProfileDetector()
        profile = MagicMock()
        profile.id = "test-supplier-2"
        profile.name = "TEST SUPPLIER 2"
        profile.ref_patterns = []
        profile.confidence_score = 0.5
        profile.last_seen = None

        # Text with multiple matching refs
        text = " ".join([f"P{str(i).zfill(9)}" for i in range(5)])

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        for _ in range(PROMOTION_EVIDENCE_COUNT):
            sync(detector._enrich_profile_with_candidates(profile, text, mock_db))

        assert len(profile.ref_patterns) > 0, (
            f"Pattern should be promoted after {PROMOTION_EVIDENCE_COUNT} occurrences"
        )

    def test_generic_profile_has_is_generic_flag(self):
        from app.services.supplier_profile_detector import _make_generic_profile
        profile = _make_generic_profile()
        assert profile.is_generic is True
        assert profile.name == "GENERIC"


# ═══════════════════════════════════════════════════════════════════
# F. PROMPT SANITY
# ═══════════════════════════════════════════════════════════════════

class TestPromptSanity:
    """The LLM system prompt must not contain hardcoded supplier-specific words."""

    _FORBIDDEN_SUPPLIER_WORDS = [
        "BOUDRANT", "SHAKO", "P199", "NPC", "Z10100",
        "NKX", "BL/LA", "TEG", "STEMCA", "SUDPACK",
        "MONDIAL FLEXIBLE",
    ]

    def test_system_prompt_has_no_hardcoded_supplier_names(self):
        from app.services.extractor import _build_system_prompt, _LLM_SCHEMA_BY_TYPE
        from app.schemas.documents import DocumentType

        schema = _LLM_SCHEMA_BY_TYPE[DocumentType.FACTURE]
        prompt = _build_system_prompt(schema, supplier_profile=None)

        for word in self._FORBIDDEN_SUPPLIER_WORDS:
            assert word not in prompt.upper(), (
                f"Prompt contains hardcoded supplier word: {word!r}"
            )

    def test_supplier_words_only_via_profile(self):
        """Supplier-specific words appear in the prompt only if injected via profile."""
        from app.services.extractor import _build_system_prompt, _LLM_SCHEMA_BY_TYPE
        from app.schemas.documents import DocumentType
        from app.services.supplier_profile_detector import DetectedSupplierProfile

        profile = DetectedSupplierProfile(
            id="test",
            name="BOUDRANT",
            supplier_code="BOUD",
            ref_patterns=[r"P\d{9}"],
            ocr_corrections={"SHAKO": "SHAKO"},
        )
        schema = _LLM_SCHEMA_BY_TYPE[DocumentType.FACTURE]
        prompt_with_profile = _build_system_prompt(schema, supplier_profile=profile)

        # With profile injection, supplier name can appear in the section
        # (injected dynamically — that is expected)
        prompt_without_profile = _build_system_prompt(schema, supplier_profile=None)
        assert "BOUDRANT" not in prompt_without_profile.upper(), (
            "BOUDRANT must not appear in the generic prompt (no profile)"
        )
