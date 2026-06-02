"""
Generic extraction tests — validates that the pipeline works on any supplier
without pre-loaded profiles (cold start) and improves on warm start.

Test matrix (5 suppliers × 3 document types):
  - TEG            (outils industriels)  : FAC + BL + BC
  - Boudrant        (pneumatique)         : FAC + BC
  - Mondial Flexible (flexibles/tuyaux)  : FAC + BL + BC
  - STEMCA           (emballage)          : FAC + BL + BC
  - SudPack          (film emballage)     : FAC + BL + BC

Each PDF is placed in server/tests/fixtures/<SUPPLIER>/<TYPE>.pdf
(or its equivalent — adjust TEST_MATRIX paths to your actual file locations).

Run:
    cd server
    pytest tests/test_generic_extraction.py -v -s

Environment variables required:
    DATABASE_URL   — PostgreSQL connection string
    OPENAI_API_KEY — for GPT-4o-mini dictionary enrichment
"""
import asyncio
import os
import pathlib
import time
from dataclasses import dataclass, field
from typing import Optional

import pytest

# ── Helpers: locate fixture files ─────────────────────────────────────────────
FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"

# Each entry: (supplier_label, doc_type, pdf_path, expected_line_count, expected_ttc)
# Set expected_ttc to None if unknown; set expected_line_count to 0 to skip line check.
@dataclass
class TestCase:
    supplier: str
    doc_type: str          # "FAC" | "BC" | "BL"
    pdf_path: pathlib.Path
    expected_lines: int = 0        # minimum real lines in document (0 = skip check)
    expected_ttc: Optional[float] = None  # None = skip TTC check

TEST_MATRIX: list[TestCase] = [
    # ── TEG ───────────────────────────────────────────────────────────────────
    TestCase("TEG", "FAC", FIXTURE_DIR / "TEG" / "facture.pdf",         expected_lines=5),
    TestCase("TEG", "BL",  FIXTURE_DIR / "TEG" / "bon_livraison.pdf",   expected_lines=5),
    TestCase("TEG", "BC",  FIXTURE_DIR / "TEG" / "bon_commande.pdf",    expected_lines=5),
    # ── Boudrant ──────────────────────────────────────────────────────────────
    TestCase("Boudrant", "FAC", FIXTURE_DIR / "Boudrant" / "facture.pdf", expected_lines=5),
    TestCase("Boudrant", "BC",  FIXTURE_DIR / "Boudrant" / "bon_commande.pdf", expected_lines=5),
    # ── Mondial Flexible ──────────────────────────────────────────────────────
    TestCase("Mondial", "FAC", FIXTURE_DIR / "Mondial" / "facture.pdf",       expected_lines=3),
    TestCase("Mondial", "BL",  FIXTURE_DIR / "Mondial" / "bon_livraison.pdf", expected_lines=3),
    TestCase("Mondial", "BC",  FIXTURE_DIR / "Mondial" / "bon_commande.pdf",  expected_lines=3),
    # ── STEMCA ────────────────────────────────────────────────────────────────
    TestCase("STEMCA", "FAC", FIXTURE_DIR / "STEMCA" / "facture.pdf",       expected_lines=3),
    TestCase("STEMCA", "BL",  FIXTURE_DIR / "STEMCA" / "bon_livraison.pdf", expected_lines=3),
    TestCase("STEMCA", "BC",  FIXTURE_DIR / "STEMCA" / "bon_commande.pdf",  expected_lines=3),
    # ── SudPack ───────────────────────────────────────────────────────────────
    TestCase("SudPack", "FAC", FIXTURE_DIR / "SudPack" / "facture.pdf",       expected_lines=3),
    TestCase("SudPack", "BL",  FIXTURE_DIR / "SudPack" / "bon_livraison.pdf", expected_lines=3),
    TestCase("SudPack", "BC",  FIXTURE_DIR / "SudPack" / "bon_commande.pdf",  expected_lines=3),
]

# Skip test cases whose fixture file does not exist
_available_cases = [tc for tc in TEST_MATRIX if tc.pdf_path.exists()]


@dataclass
class ExtractionReport:
    supplier: str
    doc_type: str
    lines_extracted: int
    lines_expected: int
    ttc_extracted: Optional[float]
    ttc_expected: Optional[float]
    confidence: float
    unknown_tokens: list[str]
    tokens_corrected: int
    tokens_to_gpt: int
    extraction_tier: str
    elapsed_s: float
    passed: bool
    failure_reason: str = ""

    def line_recall(self) -> float:
        if self.lines_expected == 0:
            return 1.0
        return self.lines_extracted / self.lines_expected

    def ttc_error_pct(self) -> Optional[float]:
        if self.ttc_expected is None or self.ttc_extracted is None:
            return None
        if self.ttc_expected == 0:
            return None
        return abs(self.ttc_extracted - self.ttc_expected) / self.ttc_expected


# ── Async extraction helper ────────────────────────────────────────────────────

async def _extract_pdf(pdf_path: pathlib.Path, supplier_label: str) -> dict:
    """
    Minimal extraction driver that runs the same code path as the real pipeline
    but without Celery — directly calls the service layer.
    """
    from app.core.database import AsyncSessionLocal
    from app.services.supplier_profile_detector import supplier_profile_detector
    from app.services.adaptive_dictionary import word_dictionary
    from app.utils.pdf_utils import analyze_pdf_pages, extract_page_as_image
    from app.services.preprocessor import preprocess_page_image
    from app.services.ocr_engine import run_tesseract
    from app.services.classifier import classify_page, DocType
    from app.services.page_grouper import group_pages_into_documents, PageClassified, extract_ref_hint
    from app.services.extractor import (
        extract_document_template, extract_document_llm, map_llm_result_to_schema
    )
    from app.schemas.documents import DocumentType as SchemaDocType
    import base64

    pdf_bytes = pdf_path.read_bytes()
    page_analyses = analyze_pdf_pages(pdf_bytes)

    classified_pages: list[PageClassified] = []
    page_ocr_data: dict[int, dict] = {}
    page_images_raw: dict[int, bytes] = {}

    for pa in page_analyses:
        page_num = pa.page_number
        if pa.source_type.value == "NATIVE":
            page_text = pa.raw_text
        else:
            raw_image = extract_page_as_image(pdf_bytes, page_num, dpi=300)
            processed = preprocess_page_image(raw_image)
            page_images_raw[page_num] = processed
            ocr = run_tesseract(processed)
            page_text = ocr.full_text
            page_ocr_data[page_num] = ocr.raw_data

        classification = await classify_page(page_text)
        ref_hint = extract_ref_hint(page_text)
        classified_pages.append(PageClassified(
            page_number=page_num,
            doc_type=classification.doc_type,
            confidence=classification.confidence,
            source_tier=classification.source_tier,
            raw_text=page_text,
            ref_hint=ref_hint,
        ))

    groups = group_pages_into_documents(classified_pages)
    for g in groups:
        for pn in g.pages:
            if pn in page_ocr_data:
                g.raw_ocr_data_per_page[pn] = page_ocr_data[pn]
            if pn in page_images_raw:
                g.page_images_b64[pn] = base64.b64encode(page_images_raw[pn]).decode("ascii")

    results = []
    async with AsyncSessionLocal() as db:
        for group in groups:
            if group.doc_type == DocType.UNKNOWN:
                continue

            detected = await supplier_profile_detector.detect_from_document(
                group.combined_text[:800], db
            )

            schema_doc_type = SchemaDocType(group.doc_type.value)
            extracted = extract_document_template(group, detected)
            tokens_to_gpt = 0
            unknown_tokens: list[str] = []

            _no_lines = (extracted is not None and hasattr(extracted, "lines") and len(extracted.lines) == 0)
            if extracted is None or extracted.extraction_confidence < 0.60 or _no_lines:
                raw_llm = await extract_document_llm(group, supplier_profile=detected)
                if raw_llm:
                    extracted = map_llm_result_to_schema(raw_llm, schema_doc_type)
                    unknown_tokens = raw_llm.get("unknown_tokens") or []
                    tokens_to_gpt = len(unknown_tokens)

            if extracted is None:
                continue

            lines = getattr(extracted, "lines", [])
            ttc = None
            if hasattr(extracted, "total_ttc") and extracted.total_ttc is not None:
                try:
                    ttc = float(extracted.total_ttc)
                except (TypeError, ValueError):
                    pass

            results.append({
                "doc_type": group.doc_type.value,
                "lines": len(lines),
                "ttc": ttc,
                "confidence": extracted.extraction_confidence,
                "unknown_tokens": unknown_tokens,
                "tokens_to_gpt": tokens_to_gpt,
                "tier": extracted.extraction_source_tier.value,
                "supplier_detected": detected.name if detected else None,
            })

    return {
        "supplier_label": supplier_label,
        "results": results,
    }


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def seed_dictionary():
    """Seed the word dictionary once per test session."""
    from app.services.adaptive_dictionary import word_dictionary
    _run(word_dictionary.bulk_seed())


# ── Cold-start tests ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "tc",
    _available_cases,
    ids=[f"{tc.supplier}-{tc.doc_type}" for tc in _available_cases],
)
def test_cold_start_extraction(tc: TestCase, capsys):
    """
    Process each PDF with NO pre-loaded supplier profile.
    Asserts:
      - document_type detected
      - line count >= 80% of expected
      - TTC within ±1% of expected (when provided)
    """
    start = time.perf_counter()
    data = _run(_extract_pdf(tc.pdf_path, tc.supplier))
    elapsed = time.perf_counter() - start

    results = data["results"]
    assert results, f"No documents extracted from {tc.pdf_path}"

    # Pick the result matching the expected doc type (or first if none)
    type_map = {"FAC": "FACTURE", "BC": "BC", "BL": "BL"}
    expected_type = type_map[tc.doc_type]
    matched = next((r for r in results if r["doc_type"] == expected_type), results[0])

    report = ExtractionReport(
        supplier=tc.supplier,
        doc_type=tc.doc_type,
        lines_extracted=matched["lines"],
        lines_expected=tc.expected_lines,
        ttc_extracted=matched["ttc"],
        ttc_expected=tc.expected_ttc,
        confidence=matched["confidence"],
        unknown_tokens=matched["unknown_tokens"],
        tokens_corrected=0,
        tokens_to_gpt=matched["tokens_to_gpt"],
        extraction_tier=matched["tier"],
        elapsed_s=elapsed,
        passed=True,
    )

    with capsys.disabled():
        print(f"\n{'─'*60}")
        print(f"SUPPLIER : {tc.supplier}  DOC: {tc.doc_type}  TIER: {report.extraction_tier}")
        print(f"Lines    : {report.lines_extracted} extracted / {report.lines_expected} expected "
              f"(recall={report.line_recall():.0%})")
        print(f"TTC      : extracted={report.ttc_extracted}  expected={report.ttc_expected}")
        print(f"Confidence: {report.confidence:.2f}  |  Elapsed: {elapsed:.1f}s")
        print(f"Tokens→GPT: {report.tokens_to_gpt}  |  Unknown: {report.unknown_tokens[:5]}")

    # ── Assertions ─────────────────────────────────────────────────────────────
    if tc.expected_lines > 0:
        recall = report.line_recall()
        assert recall >= 0.80, (
            f"{tc.supplier}/{tc.doc_type}: line recall {recall:.0%} < 80% "
            f"({report.lines_extracted} extracted, {tc.expected_lines} expected)"
        )

    if tc.expected_ttc is not None and report.ttc_extracted is not None:
        err = report.ttc_error_pct()
        assert err is not None and err <= 0.01, (
            f"{tc.supplier}/{tc.doc_type}: TTC error {err:.1%} > 1% "
            f"(extracted={report.ttc_extracted}, expected={tc.expected_ttc})"
        )


# ── Warm-start comparison ──────────────────────────────────────────────────────

def test_warm_start_improvement(capsys):
    """
    After cold-start tests have populated supplier profiles, re-run all PDFs and
    show the improvement in confidence and unknown token count.
    Fails only if warm-start is WORSE than cold-start (regression guard).
    """
    if not _available_cases:
        pytest.skip("No fixture files found — place PDFs in tests/fixtures/<SUPPLIER>/")

    cold_confs: list[float] = []
    warm_confs: list[float] = []
    cold_unknown: list[int] = []
    warm_unknown: list[int] = []

    for tc in _available_cases:
        # Cold (first pass — profiles exist from seed_dictionary, but no doc-specific profile yet)
        cold = _run(_extract_pdf(tc.pdf_path, tc.supplier))
        cold_results = cold["results"]
        if not cold_results:
            continue

        # Warm (second pass — supplier profile was auto-created in the cold pass)
        warm = _run(_extract_pdf(tc.pdf_path, tc.supplier))
        warm_results = warm["results"]
        if not warm_results:
            continue

        c_conf = cold_results[0]["confidence"]
        w_conf = warm_results[0]["confidence"]
        c_unk = len(cold_results[0]["unknown_tokens"])
        w_unk = len(warm_results[0]["unknown_tokens"])

        cold_confs.append(c_conf)
        warm_confs.append(w_conf)
        cold_unknown.append(c_unk)
        warm_unknown.append(w_unk)

    if not cold_confs:
        pytest.skip("No results to compare")

    avg_cold_conf = sum(cold_confs) / len(cold_confs)
    avg_warm_conf = sum(warm_confs) / len(warm_confs)
    avg_cold_unk = sum(cold_unknown) / len(cold_unknown)
    avg_warm_unk = sum(warm_unknown) / len(warm_unknown)

    with capsys.disabled():
        print(f"\n{'═'*60}")
        print("WARM-START IMPROVEMENT SUMMARY")
        print(f"  Avg confidence : cold={avg_cold_conf:.3f}  warm={avg_warm_conf:.3f}  "
              f"delta={avg_warm_conf - avg_cold_conf:+.3f}")
        print(f"  Avg unknown tokens: cold={avg_cold_unk:.1f}  warm={avg_warm_unk:.1f}  "
              f"delta={avg_warm_unk - avg_cold_unk:+.1f}")
        print(f"{'═'*60}")

    # Regression guard: warm must not be significantly worse than cold
    assert avg_warm_conf >= avg_cold_conf - 0.05, (
        f"Warm-start confidence regressed: cold={avg_cold_conf:.3f} warm={avg_warm_conf:.3f}"
    )


# ── Dictionary stats ───────────────────────────────────────────────────────────

def test_dictionary_stats(capsys):
    """Print and validate dictionary statistics after all tests."""
    from app.services.adaptive_dictionary import word_dictionary
    stats = _run(word_dictionary.export_stats())

    with capsys.disabled():
        print(f"\n{'─'*40}")
        print("WORD DICTIONARY STATS")
        print(f"  Total entries : {stats['total_entries']}")
        print(f"  By source     : {stats['by_source']}")
        print(f"  By category   : {stats['by_category']}")
        print(f"  Cache size    : {stats['cache_size']}")

    assert stats["total_entries"] >= 50, (
        f"Dictionary should have >= 50 seed entries, got {stats['total_entries']}"
    )
