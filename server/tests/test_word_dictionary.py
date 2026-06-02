"""
Tests for the word_dictionary system.

Covers all 20 acceptance criteria:
1-8.   OCR correction via seed (disk→DISQUE, qte→QUANTITE, etc.)
9.     Unknown normalizable token → GPT batch → correction inserted → result corrected
10-16. Protected values (codes, amounts, dates) → never touched
17.    word_dictionary never receives protected codes
18.    clean_word_dictionary marks bad entries as ignored
19.    Column headers correctly mapped
20.    canonical_form used in result when raw_form found in DB

Plus:
  - is_dictionary_candidate() with concrete examples
  - normalize_dictionary_key() output
  - GPT batch: one call, stored unverified, weight≤0.75
  - Fuzzy fallback for near-miss OCR
"""
import asyncio
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── helpers ────────────────────────────────────────────────────────────────────

def sync(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════════════════════
# is_dictionary_candidate
# ══════════════════════════════════════════════════════════════════════════════

class TestIsDictionaryCandidate:
    """Granular tests for the candidate guard."""

    from app.services.value_protection import is_dictionary_candidate

    @pytest.mark.parametrize("token,field,expected", [
        # Must return True
        ("disk",        "designation",  True),
        ("disq",        "designation",  True),
        ("racc0rd",     "designation",  True),
        ("qte",         "column_header",True),
        ("p.u.ht",      "column_header",True),
        ("desig",       "column_header",True),
        ("livraison",   "designation",  True),
        ("facture",     "designation",  True),
        ("chaine",      "designation",  True),
        ("raccord",     "designation",  True),
        # Must return False
        ("P199420414",  "article_code", False),
        ("M400010432",  "article_code", False),
        ("BCF04H",      "article_code", False),
        ("DW36PT",      "article_code", False),
        ("S096",        "article_code", False),
        ("BL2460/2025", "delivery_number", False),
        ("6 576,000",   "amount",       False),
        ("30/06/2025",  "date",         False),
        ("1200*1000*980","dimension",   False),
        ("77600",       "reference",    False),
        ("4032185",     "reference",    False),
    ])
    def test_candidate_detection(self, token, field, expected):
        from app.services.value_protection import is_dictionary_candidate
        result = is_dictionary_candidate(token, field_name=field)
        assert result == expected, (
            f"is_dictionary_candidate({token!r}, {field!r}) = {result}, expected {expected}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# normalize_dictionary_key
# ══════════════════════════════════════════════════════════════════════════════

class TestNormalizeDictionaryKey:
    @pytest.mark.parametrize("input_val,expected_key", [
        (" Disqué ",      "disque"),
        ("D1SQUE",        "d1sque"),
        ("Qté",           "qte"),
        ("Désignation",   "designation"),
        ("P.U.HT",        "p.u.ht"),
        ("Bon de Commande", "bon de commande"),
        ("  montant  ht  ", "montant ht"),
        ("racc0rd",       "racc0rd"),
    ])
    def test_normalization(self, input_val, expected_key):
        from app.services.value_protection import normalize_dictionary_key
        assert normalize_dictionary_key(input_val) == expected_key, (
            f"normalize_dictionary_key({input_val!r}) expected {expected_key!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Seed coverage — OCR corrections 1-8
# ══════════════════════════════════════════════════════════════════════════════

class TestSeedCoverage:
    """Tests 1-8: OCR tokens that must be in the seed."""

    @pytest.mark.parametrize("ocr_token,expected_canonical", [
        # Test 1-4: DISQUE variants
        ("disk",     "DISQUE"),
        ("disc",     "DISQUE"),
        ("disq",     "DISQUE"),
        ("d1sque",   "DISQUE"),
        # Test 5: RACCORD
        ("racc0rd",  "RACCORD"),
        # Test 6: QUANTITE
        ("qte",      "QUANTITE"),
        # Test 7: PRIX_UNITAIRE_HT
        ("p.u.ht",   "PRIX_UNITAIRE_HT"),
        # Test 8: DESIGNATION
        ("desig",    "DESIGNATION"),
    ])
    def test_seed_contains_mapping(self, ocr_token, expected_canonical):
        from app.services.value_protection import normalize_dictionary_key
        from app.services.adaptive_dictionary import build_full_seed_with_variants
        seed = {raw: canon for raw, canon, _ in build_full_seed_with_variants()}
        key = normalize_dictionary_key(ocr_token)
        assert key in seed, f"Seed missing key {key!r} (from OCR token {ocr_token!r})"
        assert seed[key] == expected_canonical, (
            f"{ocr_token!r} → seed[{key!r}] = {seed[key]!r}, expected {expected_canonical!r}"
        )

    @pytest.mark.parametrize("header_ocr,expected_canonical", [
        ("Qté",               "QUANTITE"),
        ("P.U.HT",            "PRIX_UNITAIRE_HT"),
        ("Total HT",          "MONTANT_HT"),
        ("Référence",         "REFERENCE"),
        ("Désignation",       "DESIGNATION"),
        ("désig",             "DESIGNATION"),
        ("qto",               "QUANTITE"),
    ])
    def test_headers_mapped(self, header_ocr, expected_canonical):
        """Test 19: Column headers correctly mapped."""
        from app.services.value_protection import normalize_dictionary_key
        from app.services.adaptive_dictionary import build_full_seed_with_variants
        seed = {raw: canon for raw, canon, _ in build_full_seed_with_variants()}
        key = normalize_dictionary_key(header_ocr)
        assert key in seed, f"Header {header_ocr!r} (key={key!r}) not in seed"
        assert seed[key] == expected_canonical, (
            f"{header_ocr!r} maps to {seed[key]!r}, expected {expected_canonical!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Protected values — tests 10-16
# ══════════════════════════════════════════════════════════════════════════════

class TestProtectedValuesNotTouched:
    """Tests 10-16: Protected tokens must pass through the dictionary unchanged."""

    @pytest.mark.parametrize("token,field", [
        ("P199420414",   "article_code"),     # test 10
        ("M400010432",   "article_code"),     # test 11
        ("BCF04H",       "article_code"),     # test 12
        ("DW36PT",       "article_code"),     # test 13
        ("BL2460/2025",  "delivery_number"),  # test 14
        ("6 576,000",    "amount"),           # test 15
        ("30/06/2025",   "date"),             # test 16
    ])
    def test_protected_returns_unchanged(self, token, field):
        from app.services.adaptive_dictionary import word_dictionary

        async def run():
            return await word_dictionary.correct(token, field_name=field)

        result, conf, source = sync(run())
        assert result == token, f"{token!r}: expected unchanged, got {result!r}"
        assert source == "PROTECTED", f"{token!r}: source should be PROTECTED, got {source!r}"

    @pytest.mark.parametrize("token", [
        "P199420414", "M400010432", "BCF04H", "DW36PT", "BL2460/2025",
        "6 576,000", "30/06/2025", "77600", "4032185",
    ])
    def test_protected_not_a_candidate(self, token):
        """Test 17: word_dictionary never receives protected codes."""
        from app.services.value_protection import is_dictionary_candidate
        assert not is_dictionary_candidate(token), (
            f"{token!r} should not be a dictionary candidate"
        )


# ══════════════════════════════════════════════════════════════════════════════
# DB lookup → canonical_form returned — test 20
# ══════════════════════════════════════════════════════════════════════════════

class TestDbLookupReturnsCanonical:
    """Test 20: When raw_form found in DB, canonical_form is returned."""

    def test_db_result_canonical_returned(self):
        from app.services.adaptive_dictionary import word_dictionary
        from app.models.word_dictionary import WordDictionaryEntry

        mock_entry = MagicMock(spec=WordDictionaryEntry)
        mock_entry.canonical_form = "DISQUE"
        mock_entry.weight = 1.0
        mock_entry.verified = True
        mock_entry.ignored = False
        mock_entry.source = "MANUAL"

        async def run():
            with patch.object(word_dictionary, "_db_lookup", new=AsyncMock(return_value=mock_entry)):
                return await word_dictionary.correct("disk", field_name="designation")

        result, conf, source = sync(run())
        assert result == "DISQUE", f"Expected DISQUE, got {result!r}"
        assert conf == 1.0


# ══════════════════════════════════════════════════════════════════════════════
# GPT batch — test 9
# ══════════════════════════════════════════════════════════════════════════════

class TestGptBatch:
    """Test 9: Unknown normalizable token → GPT batch → correction inserted → result corrected."""

    def test_unknown_word_triggers_gpt_and_stores_result(self):
        from app.services.adaptive_dictionary import word_dictionary, UnknownToken, CorrectionSuggestion

        stored: list[dict] = []
        mock_gpt_result = [
            CorrectionSuggestion(
                raw_value="racc0rd",
                corrected_value="RACCORD",
                confidence=0.92,
                term_type="product",
                should_add_to_dictionary=True,
                should_apply_now=True,
            )
        ]

        async def mock_store(raw_form, canonical, cat, weight, source,
                              verified=True, ignored=False, supplier_id=None):
            stored.append({
                "raw_form": raw_form,
                "canonical": canonical,
                "weight": weight,
                "verified": verified,
                "source": source.value if hasattr(source, "value") else str(source),
            })

        tokens = [UnknownToken(raw_value="racc0rd", field_name="designation")]

        with patch(
            "app.services.adaptive_dictionary._call_gpt_batch_correction",
            new=AsyncMock(return_value=mock_gpt_result),
        ), patch.object(word_dictionary, "_store_entry", side_effect=mock_store), \
           patch.object(word_dictionary, "_db_lookup", new=AsyncMock(return_value=None)):
            suggestions = sync(word_dictionary.correct_unknown_tokens_with_llm(tokens, {}))

        assert suggestions, "No suggestions returned"
        racc = next((s for s in suggestions if s.raw_value == "racc0rd"), None)
        assert racc is not None, "racc0rd not in suggestions"
        assert racc.corrected_value == "RACCORD"
        assert stored, "Nothing stored in DB"
        assert stored[0]["verified"] is False, "GPT result should be unverified"
        assert stored[0]["weight"] <= 0.75, "GPT weight must not exceed 0.75"
        assert "LLM_SUGGESTED" in stored[0]["source"], "Source must be LLM_SUGGESTED"

    def test_gpt_called_once_for_batch(self):
        from app.services.adaptive_dictionary import word_dictionary, UnknownToken

        call_count = 0

        async def mock_gpt(prompt: str):
            nonlocal call_count
            call_count += 1
            return []

        tokens = [
            UnknownToken(raw_value="racc0rd",  field_name="designation"),
            UnknownToken(raw_value="galvanise", field_name="designation"),
            UnknownToken(raw_value="lamele",    field_name="designation"),
        ]

        with patch(
            "app.services.adaptive_dictionary._call_gpt_batch_correction",
            side_effect=mock_gpt,
        ), patch.object(word_dictionary, "_db_lookup", new=AsyncMock(return_value=None)):
            sync(word_dictionary.correct_unknown_tokens_with_llm(tokens, {}))

        assert call_count == 1, f"Expected 1 GPT call, got {call_count}"

    def test_gpt_weight_capped(self):
        from app.services.adaptive_dictionary import word_dictionary, UnknownToken, CorrectionSuggestion

        stored_weight: list[float] = []

        async def mock_store(raw_form, canonical, cat, weight, source,
                              verified=True, ignored=False, supplier_id=None):
            stored_weight.append(weight)

        mock_result = [
            CorrectionSuggestion(
                raw_value="lamele", corrected_value="LAMELLE",
                confidence=0.99,  # high confidence — still capped
                term_type="product",
                should_add_to_dictionary=True, should_apply_now=True,
            )
        ]

        tokens = [UnknownToken(raw_value="lamele", field_name="designation")]
        with patch(
            "app.services.adaptive_dictionary._call_gpt_batch_correction",
            new=AsyncMock(return_value=mock_result),
        ), patch.object(word_dictionary, "_store_entry", side_effect=mock_store), \
           patch.object(word_dictionary, "_db_lookup", new=AsyncMock(return_value=None)):
            sync(word_dictionary.correct_unknown_tokens_with_llm(tokens, {}))

        assert stored_weight, "Nothing stored"
        assert max(stored_weight) <= 0.75, (
            f"GPT weight {max(stored_weight)} exceeds 0.75"
        )


# ══════════════════════════════════════════════════════════════════════════════
# clean_word_dictionary — test 18
# ══════════════════════════════════════════════════════════════════════════════

class TestCleanWordDictionary:
    """Test 18: clean_word_dictionary marks bad entries as ignored=True."""

    def test_bad_entries_marked_ignored(self):
        from app.models.word_dictionary import WordDictionaryEntry

        # Simulate entries: some bad, some good
        good = MagicMock(spec=WordDictionaryEntry)
        good.raw_form = "disque"
        good.canonical_form = "DISQUE"
        good.ignored = False

        bad_code = MagicMock(spec=WordDictionaryEntry)
        bad_code.raw_form = "p199420414"
        bad_code.canonical_form = "P199420414"
        bad_code.ignored = False

        bad_amount = MagicMock(spec=WordDictionaryEntry)
        bad_amount.raw_form = "6576000"
        bad_amount.canonical_form = "6576000"
        bad_amount.ignored = False

        bad_ref = MagicMock(spec=WordDictionaryEntry)
        bad_ref.raw_form = "bl2460/2025"
        bad_ref.canonical_form = "BL2460/2025"
        bad_ref.ignored = False

        all_entries = [good, bad_code, bad_amount, bad_ref]

        async def mock_execute(query):
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = all_entries
            return mock_result

        async def mock_commit():
            pass

        import app.services.clean_word_dictionary as _cwd

        async def run():
            mock_db = MagicMock()
            mock_db.execute = AsyncMock(side_effect=mock_execute)
            mock_db.commit = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)

            with patch("app.services.clean_word_dictionary.AsyncSessionLocal", return_value=mock_db):
                return await _cwd.run_cleanup(dry_run=False)

        summary = sync(run())
        assert bad_code.ignored is True, "bad_code should be marked ignored"
        assert bad_amount.ignored is True, "bad_amount should be marked ignored"
        assert bad_ref.ignored is True, "bad_ref should be marked ignored"
        assert good.ignored is False, "good entry must NOT be marked ignored"
        assert len(summary["bad_entries"]) >= 3


# ══════════════════════════════════════════════════════════════════════════════
# Bulk seed statistics
# ══════════════════════════════════════════════════════════════════════════════

class TestSeedIntegrity:
    def test_seed_has_minimum_entries(self):
        from app.services.adaptive_dictionary import build_full_seed_with_variants
        seed = build_full_seed_with_variants()
        assert len(seed) >= 200, f"Expected >= 200 seed entries, got {len(seed)}"

    def test_seed_has_no_duplicate_raw_forms(self):
        from app.services.adaptive_dictionary import build_full_seed_with_variants
        seed = build_full_seed_with_variants()
        raw_forms = [r for r, _, _ in seed]
        assert len(raw_forms) == len(set(raw_forms)), "Duplicate raw_form keys in seed"

    def test_seed_contains_no_protected_values(self):
        from app.services.adaptive_dictionary import build_full_seed_with_variants
        from app.services.value_protection import is_protected_value
        seed = build_full_seed_with_variants()
        bad = [(r, c) for r, c, _ in seed if is_protected_value(r)]
        assert not bad, f"Seed contains protected raw_forms: {bad[:10]}"

    def test_all_canonical_forms_are_uppercase(self):
        from app.services.adaptive_dictionary import _ALL_SEED_ENTRIES
        bad = [(r, c) for r, c, _ in _ALL_SEED_ENTRIES if c != c.upper()]
        assert not bad, f"Canonical forms must be uppercase, found: {bad[:5]}"


# ══════════════════════════════════════════════════════════════════════════════
# normalize_text — generic word_dictionary application on full strings
# ══════════════════════════════════════════════════════════════════════════════

class TestNormalizeText:
    """
    Tests 1-6: prove that normalize_text applies word_dictionary generically.

    No correction is hardcoded for any specific word.
    Every correction comes from the mocked DB lookup.
    """

    def _make_db_mock(self, entries: dict[str, str]):
        """Return an async _db_lookup side_effect that serves only the given entries."""
        from app.models.word_dictionary import WordDictionaryEntry

        async def _lookup(key: str):
            if key in entries:
                m = MagicMock(spec=WordDictionaryEntry)
                m.canonical_form = entries[key]
                m.weight = 1.0
                m.verified = True
                m.ignored = False
                m.source = "MANUAL"
                return m
            return None

        return _lookup

    def test_generic_correction_blous(self):
        """Test 1: blous → BLOCUS — correction comes from DB, not hardcoded."""
        from app.services.adaptive_dictionary import word_dictionary

        async def run():
            word_dictionary._cache = {}
            with patch.object(
                word_dictionary, "_db_lookup",
                side_effect=self._make_db_mock({"blous": "BLOCUS"}),
            ), patch.object(word_dictionary, "_fuzzy_match", new=AsyncMock(return_value=None)):
                return await word_dictionary.normalize_text(
                    "CADNA BLOUS LAITON 60MM", field_name="designation"
                )

        result = sync(run())
        assert "BLOCUS" in result, f"blous must be corrected to BLOCUS, got: {result!r}"
        assert "BLOUS" not in result, f"raw BLOUS must not remain, got: {result!r}"
        assert "60MM" in result, f"dimension 60MM must be preserved, got: {result!r}"

    def test_generic_correction_disk(self):
        """Test 2: disk → DISQUE."""
        from app.services.adaptive_dictionary import word_dictionary

        async def run():
            word_dictionary._cache = {}
            with patch.object(
                word_dictionary, "_db_lookup",
                side_effect=self._make_db_mock({"disk": "DISQUE"}),
            ), patch.object(word_dictionary, "_fuzzy_match", new=AsyncMock(return_value=None)):
                return await word_dictionary.normalize_text(
                    "DISK A LAMELLE", field_name="designation"
                )

        result = sync(run())
        assert result == "DISQUE A LAMELLE", f"Got: {result!r}"

    def test_generic_correction_racc0rd(self):
        """Test 3: racc0rd → RACCORD."""
        from app.services.adaptive_dictionary import word_dictionary

        async def run():
            word_dictionary._cache = {}
            with patch.object(
                word_dictionary, "_db_lookup",
                side_effect=self._make_db_mock({"racc0rd": "RACCORD"}),
            ), patch.object(word_dictionary, "_fuzzy_match", new=AsyncMock(return_value=None)):
                return await word_dictionary.normalize_text(
                    "SHAKO RACC0RD DROIT", field_name="designation"
                )

        result = sync(run())
        assert result == "SHAKO RACCORD DROIT", f"Got: {result!r}"

    def test_generic_correction_qte(self):
        """Test 4: qte → QUANTITE (single-token text)."""
        from app.services.adaptive_dictionary import word_dictionary

        async def run():
            word_dictionary._cache = {}
            with patch.object(
                word_dictionary, "_db_lookup",
                side_effect=self._make_db_mock({"qte": "QUANTITE"}),
            ), patch.object(word_dictionary, "_fuzzy_match", new=AsyncMock(return_value=None)):
                return await word_dictionary.normalize_text("QTE", field_name="designation")

        result = sync(run())
        assert result == "QUANTITE", f"Got: {result!r}"

    def test_ignored_entry_not_applied(self):
        """Test 5: entries with ignored=True must never correct tokens."""
        from app.services.adaptive_dictionary import word_dictionary
        from app.models.word_dictionary import WordDictionaryEntry

        async def _lookup_ignored(key: str):
            if key == "abc":
                m = MagicMock(spec=WordDictionaryEntry)
                m.canonical_form = "XXX"
                m.weight = 1.0
                m.verified = True
                m.ignored = True  # must NOT be applied
                m.source = "MANUAL"
                return m
            return None

        async def run():
            word_dictionary._cache = {}
            with patch.object(
                word_dictionary, "_db_lookup", side_effect=_lookup_ignored
            ), patch.object(word_dictionary, "_fuzzy_match", new=AsyncMock(return_value=None)):
                return await word_dictionary.normalize_text("ABC", field_name="designation")

        result = sync(run())
        assert result == "ABC", f"ignored entry must not be applied, got: {result!r}"

    def test_protected_values_preserved(self):
        """Test 6: product codes, dimensions, amounts are never altered."""
        from app.services.adaptive_dictionary import word_dictionary

        async def run():
            word_dictionary._cache = {}
            with patch.object(
                word_dictionary, "_db_lookup",
                side_effect=self._make_db_mock({"blous": "BLOCUS"}),
            ), patch.object(word_dictionary, "_fuzzy_match", new=AsyncMock(return_value=None)):
                return await word_dictionary.normalize_text(
                    "P198602123 CADNA BLOUS LAITON 60MM 45,08",
                    field_name="designation",
                )

        result = sync(run())
        assert result == "P198602123 CADNA BLOCUS LAITON 60MM 45,08", f"Got: {result!r}"
        assert "P198602123" in result, "product code must be preserved"
        assert "BLOCUS" in result, "blous must be corrected to BLOCUS"
        assert "60MM" in result, "dimension must be preserved"
        assert "45,08" in result, "amount must be preserved"


# ══════════════════════════════════════════════════════════════════════════════
# D — New tests for Problems 1 & 2 (cache fix + renormalize + page ordering)
# ══════════════════════════════════════════════════════════════════════════════

class TestCacheDoesNotBlockNewDBEntry:
    """
    D6: A stale PASSTHROUGH or LLM-no-op result in the cache must NOT prevent
    a later MANUAL DB entry from being applied on the next call.
    """

    def test_passthrough_then_manual_entry_found(self):
        """
        Sequence:
          1. correct("BLOUS") → DB miss → PASSTHROUGH (not cached)
          2. MANUAL entry blous→BLOCUS is added to DB
          3. correct("BLOUS") → DB hit → returns BLOCUS
        """
        from app.services.adaptive_dictionary import word_dictionary
        from app.models.word_dictionary import WordDictionaryEntry

        entry = MagicMock(spec=WordDictionaryEntry)
        entry.canonical_form = "BLOCUS"
        entry.weight = 1.0
        entry.verified = True
        entry.ignored = False
        entry.source = "MANUAL"

        call_count = {"n": 0}

        async def _lookup_after_add(key: str):
            # First call: not in DB yet. Second call: MANUAL entry present.
            call_count["n"] += 1
            if call_count["n"] >= 2 and key == "blous":
                return entry
            return None

        async def run():
            word_dictionary._cache = {}
            with patch.object(
                word_dictionary, "_db_lookup", side_effect=_lookup_after_add
            ), patch.object(word_dictionary, "_fuzzy_match", new=AsyncMock(return_value=None)):
                first = await word_dictionary.correct("BLOUS", field_name="designation")
                # Simulate adding a MANUAL entry: cache must stay clear (PASSTHROUGH not cached)
                second = await word_dictionary.correct("BLOUS", field_name="designation")
            return first, second

        first, second = sync(run())
        assert first[0] == "BLOUS", f"First call (no DB entry) must return original, got {first[0]!r}"
        assert first[2] == "PASSTHROUGH", f"First call source must be PASSTHROUGH, got {first[2]!r}"
        assert second[0] == "BLOCUS", f"Second call (DB entry present) must return BLOCUS, got {second[0]!r}"

    def test_llm_noop_not_cached(self):
        """
        A GPT suggestion where corrected_value == raw_value must NOT be stored
        in the cache so that a later DB lookup can still correct the word.
        """
        from app.services.adaptive_dictionary import word_dictionary, UnknownToken, CorrectionSuggestion
        from app.models.word_dictionary import WordDictionaryEntry

        # GPT returns "blous" unchanged (no-op suggestion)
        noop_suggestion = [
            CorrectionSuggestion(
                raw_value="blous",
                corrected_value="blous",  # no actual correction
                confidence=0.72,
                term_type="product",
                should_add_to_dictionary=True,
                should_apply_now=True,
            )
        ]

        entry = MagicMock(spec=WordDictionaryEntry)
        entry.canonical_form = "BLOCUS"
        entry.weight = 1.0
        entry.verified = True
        entry.ignored = False
        entry.source = "MANUAL"

        async def run():
            word_dictionary._cache = {}
            tokens = [UnknownToken(raw_value="blous", field_name="designation")]
            with patch(
                "app.services.adaptive_dictionary._call_gpt_batch_correction",
                new=AsyncMock(return_value=noop_suggestion),
            ), patch.object(word_dictionary, "_db_lookup", new=AsyncMock(return_value=None)), \
               patch.object(word_dictionary, "_store_entry", new=AsyncMock()):
                await word_dictionary.correct_unknown_tokens_with_llm(tokens, {})

            # After GPT no-op, cache must NOT have "blous"
            from app.services.value_protection import normalize_dictionary_key
            assert normalize_dictionary_key("blous") not in word_dictionary._cache, (
                "No-op GPT suggestion must not be cached"
            )

            # Now a MANUAL entry appears in DB → must be found on next correct() call
            with patch.object(
                word_dictionary, "_db_lookup", new=AsyncMock(return_value=entry)
            ), patch.object(word_dictionary, "_fuzzy_match", new=AsyncMock(return_value=None)):
                result, _, source = await word_dictionary.correct(
                    "BLOUS", field_name="designation"
                )

            return result, source

        result, source = sync(run())
        assert result == "BLOCUS", f"After no-op GPT, MANUAL entry must be used, got {result!r}"

    def test_invalidate_cache_key_clears_entry(self):
        """clear_cache and invalidate_cache_key must evict stale entries."""
        from app.services.adaptive_dictionary import word_dictionary

        word_dictionary._cache["blous"] = ("BLOUS", 0.5, "LLM_SUGGESTED")
        removed = word_dictionary.invalidate_cache_key("blous")
        assert removed is True, "invalidate_cache_key must return True when entry was present"
        assert "blous" not in word_dictionary._cache, "Cache entry must be removed"

    def test_clear_cache_empties_all(self):
        from app.services.adaptive_dictionary import word_dictionary

        word_dictionary._cache["foo"] = ("FOO", 1.0, "MANUAL")
        word_dictionary._cache["bar"] = ("BAR", 1.0, "MANUAL")
        count = word_dictionary.clear_cache()
        assert count >= 2, f"Expected >= 2 cleared, got {count}"
        assert len(word_dictionary._cache) == 0, "Cache must be empty after clear_cache()"


class TestUsageCountIncrements:
    """D2: usage_count must increment when a word is corrected from the DB."""

    def test_usage_count_incremented_on_db_hit(self):
        from app.services.adaptive_dictionary import word_dictionary
        from app.models.word_dictionary import WordDictionaryEntry

        entry = MagicMock(spec=WordDictionaryEntry)
        entry.canonical_form = "BLOCUS"
        entry.weight = 1.0
        entry.verified = True
        entry.ignored = False
        entry.source = "MANUAL"

        incremented: list[str] = []

        async def mock_increment(key: str):
            incremented.append(key)

        async def run():
            word_dictionary._cache = {}
            with patch.object(
                word_dictionary, "_db_lookup", new=AsyncMock(return_value=entry)
            ), patch.object(
                word_dictionary, "_increment_usage", side_effect=mock_increment
            ), patch.object(word_dictionary, "_fuzzy_match", new=AsyncMock(return_value=None)):
                return await word_dictionary.correct("BLOUS", field_name="designation")

        result, _, _ = sync(run())
        assert result == "BLOCUS", f"Expected BLOCUS, got {result!r}"
        assert incremented, "usage_count must be incremented after DB hit"
        assert "blous" in incremented, f"Expected 'blous' incremented, got {incremented}"


class TestRenormalizeService:
    """D7: renormalize_saved_job must update stored designations from word_dictionary."""

    def test_renormalize_updates_designation(self):
        from app.services.renormalize_service import renormalize_saved_job
        from app.services.adaptive_dictionary import word_dictionary
        from app.models.job import Job
        from app.models.document import Document
        from app.models.line_item import LineItem

        li = MagicMock(spec=LineItem)
        li.id = "line-001"
        li.designation = "CADNA BLOUS LAITON 60MM"
        li.raw_designation = "CADNA BLOUS LAITON 60MM"

        doc = MagicMock(spec=Document)
        doc.doc_type = "BC"
        doc.line_items = [li]

        job = MagicMock(spec=Job)
        job.id = "job-001"

        updated_values: list[str] = []

        async def run():
            word_dictionary._cache = {}

            mock_db = MagicMock()
            mock_db.commit = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)

            # Job query
            job_res = MagicMock()
            job_res.scalar_one_or_none.return_value = job

            # Documents query
            docs_res = MagicMock()
            docs_res.scalars.return_value.all.return_value = [doc]

            call_count = {"n": 0}

            async def _execute(q):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return job_res
                if call_count["n"] == 2:
                    return docs_res
                # UPDATE calls
                updated_values.append("updated")
                return MagicMock()

            mock_db.execute = AsyncMock(side_effect=_execute)

            from app.models.word_dictionary import WordDictionaryEntry
            db_entry = MagicMock(spec=WordDictionaryEntry)
            db_entry.canonical_form = "BLOCUS"
            db_entry.weight = 1.0
            db_entry.verified = True
            db_entry.ignored = False
            db_entry.source = "MANUAL"

            with patch.object(
                word_dictionary, "_db_lookup",
                side_effect=lambda key: AsyncMock(
                    return_value=db_entry if key == "blous" else None
                )(),
            ), patch.object(word_dictionary, "_fuzzy_match", new=AsyncMock(return_value=None)), \
               patch.object(word_dictionary, "_increment_usage", new=AsyncMock()):
                return await renormalize_saved_job("job-001", mock_db)

        report = sync(run())
        assert report["lines_scanned"] == 1, f"Expected 1 line scanned, got {report['lines_scanned']}"
        assert report["lines_modified"] == 1, f"Expected 1 modified, got {report['lines_modified']}"
        assert report["corrections"][0]["after"] == "CADNA BLOCUS LAITON 60MM", (
            f"Expected corrected designation, got {report['corrections'][0]['after']!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# H — P2 tests: page ordering and multi-line / duplicate article extraction
# ══════════════════════════════════════════════════════════════════════════════

class TestPrintedPageOrdering:
    """
    H1: Pages must be sorted by their printed page number before LLM extraction.
    """

    def test_extract_printed_page_number(self):
        from app.services.extractor import _extract_printed_page_number
        assert _extract_printed_page_number("BON DE COMMANDE\nPAGE : 1 *Suite*\n") == 1
        assert _extract_printed_page_number("BON DE COMMANDE\nPAGE : 2\nTOTAL") == 2
        assert _extract_printed_page_number("PAGE 3\n") == 3
        assert _extract_printed_page_number("No page info here") is None

    def test_reorder_swaps_pages_when_pdf_order_is_reversed(self):
        """
        When the PDF has page-2 (blank summary) before page-1 (items), the
        reorder function must put page-1 first in the combined OCR text.
        """
        from app.services.extractor import _reorder_group_by_printed_pages
        from app.services.page_grouper import DocumentGroup

        text_page_pdf2 = "BON DE COMMANDE\nPAGE : 2\nTOTAL HORS TAXES 777.225\n"
        text_page_pdf3 = "BON DE COMMANDE\nPAGE : 1 *Suite*\nP199680136 DISQUE A LAMELLE\n"

        group = DocumentGroup(
            doc_type="BC",
            pages=[2, 3],
            combined_text=text_page_pdf2 + "\n" + text_page_pdf3,
            page_texts={2: text_page_pdf2, 3: text_page_pdf3},
            page_images_b64={2: "img2", 3: "img3"},
        )

        reordered_text, ordered_pages = _reorder_group_by_printed_pages(group)

        assert ordered_pages == [3, 2], (
            f"Expected PDF pages [3, 2] (items first), got {ordered_pages}"
        )
        assert reordered_text.index("DISQUE A LAMELLE") < reordered_text.index("TOTAL HORS TAXES"), (
            "Items page content must appear before totals page content in reordered text"
        )

    def test_no_reorder_when_single_page(self):
        from app.services.extractor import _reorder_group_by_printed_pages
        from app.services.page_grouper import DocumentGroup

        text = "FACTURE\nPAGE : 1\nItem1\n"
        group = DocumentGroup(
            doc_type="FACTURE",
            pages=[1],
            combined_text=text,
            page_texts={1: text},
            page_images_b64={1: "img1"},
        )
        reordered_text, ordered_pages = _reorder_group_by_printed_pages(group)
        assert ordered_pages == [1]
        assert reordered_text == text

    def test_no_reorder_when_printed_numbers_missing(self):
        """Falls back to original order when page numbers cannot be detected."""
        from app.services.extractor import _reorder_group_by_printed_pages
        from app.services.page_grouper import DocumentGroup

        t1 = "Item list\n"
        t2 = "Totals\n"
        group = DocumentGroup(
            doc_type="BC",
            pages=[1, 2],
            combined_text=t1 + "\n" + t2,
            page_texts={1: t1, 2: t2},
            page_images_b64={1: "img1", 2: "img2"},
        )
        reordered_text, ordered_pages = _reorder_group_by_printed_pages(group)
        assert ordered_pages == [1, 2], "No printed numbers → original PDF order must be kept"


class TestVisibleRefCounting:
    """
    H2: _count_visible_article_refs must count distinct article codes in OCR text.
    """

    def test_counts_p_style_refs(self):
        from app.services.extractor import _count_visible_article_refs
        text = (
            "P199680136 DISQUE A LAMELLE\n"
            "P199602050 CADENA LAITON\n"
            "P199602123 CADENA LAITON\n"
            "P199642013 CHAINE\n"
            "TOTAL HORS TAXES 777.225\n"
        )
        count = _count_visible_article_refs(text)
        assert count == 4, f"Expected 4 unique P-refs, got {count}"

    def test_duplicate_ref_counted_once(self):
        from app.services.extractor import _count_visible_article_refs
        text = "P199403542 MECHE 5MM qty=2\nP199403542 MECHE 5MM qty=5\n"
        count = _count_visible_article_refs(text)
        assert count == 1, f"Same ref on two rows must count as 1 unique ref, got {count}"

    def test_totals_lines_not_counted_as_refs(self):
        from app.services.extractor import _count_visible_article_refs
        text = "TOTAL HORS TAXES 777.225\nNET A PAYER 786.165\nREMISE 116.583\n"
        count = _count_visible_article_refs(text)
        assert count == 0, f"Total/footer lines must not be counted as article refs, got {count}"
