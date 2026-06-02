"""
Main processing pipeline — orchestrates all layers in sequence.
Runs in the pdf_processing Celery queue (CPU-bound workers).
"""
import asyncio
import base64
from datetime import datetime, timezone
from celery import Task
from sqlalchemy.ext.asyncio import AsyncSession
import sys
from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal, engine
from app.core.storage import storage_client
from app.core.logging import get_logger
from app.core.config import settings
from app.models.job import Job, JobStatus, GlobalVerdict as JobGlobalVerdict
from app.models.document import Document, DocumentType, ExtractionSourceTier, PageSourceType
from app.models.line_item import LineItem
from app.models.match_result import MatchResult
from app.models.audit_log import AuditLog
from app.utils.pdf_utils import analyze_pdf_pages, extract_page_as_image
from app.services.preprocessor import preprocess_page_image
from app.services.ocr_engine import run_tesseract
from app.services.classifier import classify_page, DocType
from app.services.page_grouper import (
    group_pages_into_documents, PageClassified, extract_ref_hint
)
from app.services.supplier_service import get_supplier_from_text
from app.services.supplier_profile_detector import supplier_profile_detector
from app.services.adaptive_dictionary import word_dictionary, UnknownToken
from app.services.value_protection import is_protected_value
from app.services.extractor import (
    extract_document_template, extract_document_llm, map_llm_result_to_schema,
)
from app.services.validator import validate_bc, validate_bl, validate_facture, validate_date_ordering
from app.services.matcher import run_three_way_match
from app.services.reference_aliases import (
    load_reference_alias_map,
    mark_aliases_used,
)
from app.schemas.documents import BonDeCommandeSchema, BonDeLivraison, FactureSchema, DocumentType as SchemaDocType
logger = get_logger(__name__)

def run_async(coro):
    """
    Run an async coroutine from a synchronous Celery task context.

    On Windows, asyncio.run() closes the ProactorEventLoop which invalidates
    all asyncpg socket transports held in the SQLAlchemy connection pool.
    Disposing the pool here ensures the next call gets fresh connections on
    the new event loop. On POSIX systems this disposal is unnecessary and
    wastes pool warm-up time, so we skip it.
    """
    try:
        return asyncio.run(coro)
    finally:
        if sys.platform == "win32":
            engine.sync_engine.dispose()


@celery_app.task(
    bind=True,
    name="app.workers.pipeline.process_document_pipeline",
    queue="pdf_processing",
    max_retries=2,
    default_retry_delay=15,
    acks_late=True,
)
def process_document_pipeline(self: Task, job_id: str) -> dict:
    """
    Full pipeline task. Runs synchronously in Celery but uses asyncio internally
    for database operations.
    """
    print(f"\n{'='*80}")
    print(f"🚀 PIPELINE STARTED | Job: {job_id}")
    print(f"{'='*80}\n")

    try:
        return run_async(_run_pipeline(job_id))
    except Exception as exc:
        print(f"\n{'='*80}")
        print(f"❌ PIPELINE FAILED | Job: {job_id}")
        print(f"Error: {str(exc)}")
        print(f"{'='*80}\n")

        is_final_attempt = self.request.retries >= self.max_retries
        if is_final_attempt:
            run_async(_mark_job_failed(job_id, str(exc)))
        else:
            print(f"🔄 Retrying... Attempt {self.request.retries + 1}/{self.max_retries}\n")

        raise self.retry(exc=exc)


async def _run_pipeline(job_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        # ── Update job status ──────────────────────────────────────────
        job = await _get_job(db, job_id)
        job.status = JobStatus.PROCESSING
        job.processing_started_at = datetime.now(timezone.utc)
        await db.commit()
        await _audit(db, job_id, "PIPELINE_STARTED", {"job_id": job_id})

        # ── Layer 0: Download PDF ──────────────────────────────────────
        print("📥 Layer 0: Downloading PDF...")
        pdf_bytes = storage_client.download_pdf(job.original_pdf_key)

        # ── Layer 1: PDF Analysis — native vs scanned ──────────────────
        print("📄 Layer 1: Analyzing PDF structure...")
        page_analyses = analyze_pdf_pages(pdf_bytes)
        native_count = sum(1 for p in page_analyses if p.source_type.value == "NATIVE")
        scanned_count = sum(1 for p in page_analyses if p.source_type.value == "SCANNED")
        print(f"   ✓ {len(page_analyses)} pages | {native_count} native | {scanned_count} scanned\n")
        await _audit(db, job_id, "PDF_ANALYZED", {
            "page_count": len(page_analyses),
            "native_pages": native_count,
            "scanned_pages": scanned_count,
        })

        # ── Layers 2–3: Preprocess + Classify each page ────────────────
        print("🔍 Layers 2-3: OCR + Classification...")
        job.status = JobStatus.CLASSIFYING
        await db.commit()
        classified_pages: list[PageClassified] = []
        page_ocr_data: dict[int, dict] = {}
        page_ocr_source: dict[int, str] = {}
        page_ocr_confidence: dict[int, float] = {}
        page_images_raw: dict[int, bytes] = {}
        for page_analysis in page_analyses:
            page_num = page_analysis.page_number
            page_image_b64: str | None = None
            if page_analysis.source_type.value == "NATIVE":
                page_text = page_analysis.raw_text
                page_ocr_source[page_num] = "native"
            else:
                raw_image = extract_page_as_image(pdf_bytes, page_num, dpi=400)
                processed_image = preprocess_page_image(raw_image)
                storage_client.upload_page_image(job_id, page_num, processed_image)
                page_images_raw[page_num] = processed_image
                page_image_b64 = base64.b64encode(processed_image).decode("ascii")
                use_gemini_ocr = (
                    bool(getattr(settings, "use_parallel_vision", False))
                    and bool(getattr(settings, "gemini_api_key", "").strip())
                )
                if use_gemini_ocr:
                    from app.workers.llm_worker import extract_page_text_gemini

                    ocr_result, gemini_text = await asyncio.gather(
                        asyncio.to_thread(run_tesseract, processed_image),
                        extract_page_text_gemini(page_image_b64, page_number=page_num),
                    )
                else:
                    ocr_result = await asyncio.to_thread(run_tesseract, processed_image)
                    gemini_text = None

                page_text, selected_ocr_source = _select_ocr_text(
                    tesseract_text=ocr_result.full_text,
                    tesseract_confidence=ocr_result.mean_confidence,
                    gemini_text=gemini_text,
                )
                page_ocr_data[page_num] = ocr_result.raw_data
                page_ocr_source[page_num] = selected_ocr_source
                page_ocr_confidence[page_num] = ocr_result.mean_confidence
                await _audit(db, job_id, "PAGE_OCR_COMPLETED", {
                    "page_number": page_num,
                    "selected_source": selected_ocr_source,
                    "tesseract_confidence": round(ocr_result.mean_confidence, 3),
                    "tesseract_chars": len(ocr_result.full_text or ""),
                    "gemini_chars": len(gemini_text or ""),
                })
            classification = await classify_page(page_text, image_b64=page_image_b64)
            print(f"   Page {page_num}: {classification.doc_type.value} ({int(classification.confidence*100)}%)")
            await _audit(db, job_id, "PAGE_CLASSIFIED", {
                "page_number": page_num,
                "doc_type": classification.doc_type,
                "confidence": classification.confidence,
                "source_tier": classification.source_tier,
                "source_type": page_analysis.source_type.value,
                "ocr_source": page_ocr_source.get(page_num),
                "ocr_confidence": page_ocr_confidence.get(page_num),
            })
            if classification.doc_type == DocType.UNKNOWN:
                job.status = JobStatus.REVIEW_REQUIRED
                await db.commit()
                await _audit(db, job_id, "PAGE_REQUIRES_HUMAN_CLASSIFICATION", {
                    "page_number": page_num,
                    "reasoning": classification.reasoning,
                })
            ref_hint = extract_ref_hint(page_text)
            classified_pages.append(PageClassified(
                page_number=page_num,
                doc_type=classification.doc_type,
                confidence=classification.confidence,
                source_tier=classification.source_tier,
                raw_text=page_text,
                ref_hint=ref_hint,
            ))
        print()

        # ── Layer 4: Group pages into document units ───────────────────
        print("📑 Layer 4: Grouping pages...")
        document_groups = group_pages_into_documents(classified_pages)
        for group in document_groups:
            print(f"   {group.doc_type.value}: pages {group.pages}")
            group_uses_gemini_text = any(
                page_ocr_source.get(pn) == "gemini" for pn in group.pages
            )
            for pn in group.pages:
                if (
                    not group_uses_gemini_text
                    and pn in page_ocr_data
                    and page_ocr_source.get(pn) == "tesseract"
                ):
                    group.raw_ocr_data_per_page[pn] = page_ocr_data[pn]
                if pn in page_images_raw:
                    group.page_images_b64[pn] = base64.b64encode(page_images_raw[pn]).decode("ascii")
        print()
        await _audit(db, job_id, "PAGES_GROUPED", {
            "groups": [
                {"doc_type": g.doc_type, "pages": g.pages, "ref_hint": g.ref_document}
                for g in document_groups
            ]
        })

        # ── Layer 5: Extract each document group ──────────────────────
        print("📊 Layer 5: Extracting data...")
        job.status = JobStatus.EXTRACTING
        await db.commit()
        extracted_documents: dict[str, BonDeCommandeSchema | BonDeLivraison | FactureSchema] = {}
        supplier_alias_scopes: dict[str, dict[str, str | None]] = {}

        def remember_supplier_alias_scope(doc_key: str, extracted_doc, detected_profile) -> None:
            profile_is_specific = detected_profile and not getattr(detected_profile, "is_generic", False)
            supplier_alias_scopes[doc_key] = {
                "supplier_id": detected_profile.id if profile_is_specific else None,
                "supplier_code": (
                    getattr(detected_profile, "supplier_code", None)
                    if profile_is_specific else None
                ),
                "supplier_name": (
                    getattr(extracted_doc, "supplier_name", None)
                    or (detected_profile.name if profile_is_specific else None)
                ),
            }

        for group in document_groups:
            print(f"   Extracting {group.doc_type.value}...", end="")
            if group.doc_type == DocType.UNKNOWN:
                continue # TODO: Handle unknown doc type
            header_text = group.combined_text[:500]
            legacy_profile = await get_supplier_from_text(header_text, db)
            if legacy_profile is not None:
                detected_profile = legacy_profile
            else:
                detected_profile = await supplier_profile_detector.detect_from_document(
                    group.combined_text[:800], db
                )
                if detected_profile:
                    await _audit(db, job_id, "SUPPLIER_AUTO_DETECTED", {
                        "supplier": detected_profile.name,
                        "code": detected_profile.supplier_code,
                        "auto_detected": detected_profile.auto_detected,
                        "ref_patterns": detected_profile.ref_patterns,
                    })

            schema_doc_type = SchemaDocType(group.doc_type.value)
            group_uses_gemini_text = any(
                page_ocr_source.get(pn) == "gemini" for pn in group.pages
            )

            if group_uses_gemini_text:
                extracted = None
                _has_no_lines = False
                await _audit(db, job_id, "TEMPLATE_SKIPPED_GEMINI_OCR", {
                    "doc_type": group.doc_type,
                    "pages": group.pages,
                    "reason": (
                        "Gemini OCR text is clean but not column-aligned for "
                        "the legacy template parser; using GPT-4o extraction "
                        "with Gemini OCR as context."
                    ),
                })
            else:
                extracted = await extract_document_template(group, detected_profile)
                _has_no_lines = (
                    extracted is not None
                    and hasattr(extracted, "lines")
                    and len(extracted.lines) == 0
                )

            if (
                group_uses_gemini_text
                or extracted is None
                or extracted.extraction_confidence < 0.60
                or _has_no_lines
            ):
                await _audit(db, job_id, "LLM_FALLBACK_TRIGGERED", {
                    "doc_type": group.doc_type,
                    "pages": group.pages,
                    "reason": (
                        "Gemini OCR text used; template intentionally skipped"
                        if group_uses_gemini_text
                        else (
                            "Template extraction produced 0 line items"
                            if _has_no_lines
                            else "Template extraction confidence too low or failed"
                        )
                    ),
                })
                extracted = None

                raw_extraction: dict | None = None

                if extracted is None:
                    await _audit(db, job_id, "GPT_FALLBACK_TRIGGERED", {
                        "doc_type": group.doc_type,
                        "pages": group.pages,
                        "reason": (
                            "Gemini OCR text used as clean context"
                            if group_uses_gemini_text
                            else "Template extraction failed or was low confidence"
                        ),
                    })
                    raw_llm = await extract_document_llm(
                        group, supplier_profile=detected_profile
                    )
                    if raw_llm:
                        extracted = await map_llm_result_to_schema(raw_llm, schema_doc_type)
                        raw_extraction = raw_llm if extracted is not None else None

                        if extracted is None:
                            raw_llm_retry = await extract_document_llm(
                                group,
                                validation_error=(
                                    "Previous extraction returned incomplete data. "
                                    "Ensure all required fields are present."
                                ),
                                supplier_profile=detected_profile,
                            )
                            if raw_llm_retry:
                                extracted = await map_llm_result_to_schema(raw_llm_retry, schema_doc_type)
                                raw_extraction = raw_llm_retry if extracted is not None else None

                if raw_extraction and isinstance(raw_extraction, dict):
                    unknown_tokens_raw: list[str] = raw_extraction.get("unknown_tokens") or []
                    unknown_tokens_raw = [
                        t for t in unknown_tokens_raw[:20]
                        if t and not is_protected_value(t)
                    ]
                    if unknown_tokens_raw:
                        await _audit(db, job_id, "DICTIONARY_ENRICHMENT_TRIGGERED", {
                            "doc_type": group.doc_type,
                            "unknown_tokens": unknown_tokens_raw,
                        })
                        supplier_id = (
                            detected_profile.id
                            if detected_profile and not detected_profile.is_generic
                            else None
                        )
                        batch_tokens = [
                            UnknownToken(
                                raw_value=tok,
                                context_words=_extract_context_words(
                                    group.combined_text, tok, window=5
                                ),
                                supplier_id=supplier_id,
                            )
                            for tok in unknown_tokens_raw
                        ]
                        gpt_context = {
                            "supplier_name": detected_profile.name if detected_profile else None,
                            "doc_type": group.doc_type.value,
                        }
                        await word_dictionary.correct_unknown_tokens_with_llm(
                            batch_tokens, gpt_context
                        )

            if extracted is None:
                print(" ❌ Failed")
                await _audit(db, job_id, "EXTRACTION_FAILED", {
                    "doc_type": group.doc_type,
                    "pages": group.pages,
                })
                job.status = JobStatus.REVIEW_REQUIRED
                await db.commit()
                continue
            print(" ✓")

            # ── Layer 6: Correction + Normalization already applied in extractor ──

            # ── Layer 7: Validation ───────────────────────────────────
            if isinstance(extracted, BonDeCommandeSchema):
                val_result = validate_bc(extracted)
                existing_bc = extracted_documents.get("BC")
                if existing_bc is None or len(extracted.lines) >= len(existing_bc.lines):
                    extracted_documents["BC"] = extracted
                    remember_supplier_alias_scope("BC", extracted, detected_profile)
            elif isinstance(extracted, BonDeLivraison):
                val_result = validate_bl(extracted)
                if "BL" not in extracted_documents:
                    extracted_documents["BL"] = []
                extracted_documents["BL"].append(extracted)
                if "BL" not in supplier_alias_scopes:
                    remember_supplier_alias_scope("BL", extracted, detected_profile)
            elif isinstance(extracted, FactureSchema):
                val_result = validate_facture(extracted)
                existing_fac = extracted_documents.get("FACTURE")
                if existing_fac is None or len(extracted.lines) > len(existing_fac.lines):
                    extracted_documents["FACTURE"] = extracted
                    remember_supplier_alias_scope("FACTURE", extracted, detected_profile)
            else:
                continue

            await _audit(db, job_id, "DOCUMENT_VALIDATED", {
                "doc_type": group.doc_type,
                "is_valid": val_result.is_valid,
                "errors": val_result.errors,
                "warnings": val_result.warnings,
            })
            doc_model = Document(
                job_id=job_id,
                doc_type=DocumentType(group.doc_type.value),
                page_numbers=group.pages,
                classification_confidence=group.classification_confidence,
                classification_source_tier=group.source_tier,
                extraction_confidence=extracted.extraction_confidence,
                extraction_source_tier=ExtractionSourceTier(extracted.extraction_source_tier.value),
                has_low_confidence_fields=extracted.has_low_confidence_fields,
                supplier_id=(
                    detected_profile.id
                    if detected_profile and not getattr(detected_profile, "is_generic", False)
                    else None
                ),
                supplier_name_raw=extracted.supplier_name if hasattr(extracted, "supplier_name") else None,
                ref_document=_get_ref(extracted),
                ref_bc_linked=extracted.ref_bc_linked if hasattr(extracted, "ref_bc_linked") else None,
                document_date=extracted.document_date,
                total_ht=float(extracted.total_ht) if hasattr(extracted, "total_ht") and extracted.total_ht else None,
                total_ttc=float(extracted.total_ttc) if hasattr(extracted, "total_ttc") and extracted.total_ttc else None,
                tva_rate=float(extracted.tva_rate) if hasattr(extracted, "tva_rate") and extracted.tva_rate else None,
                raw_extracted_data=extracted.model_dump(mode="json"),
                field_confidence_map=extracted.field_confidence_map,
                requires_review=not val_result.is_valid or extracted.has_low_confidence_fields,
            )
            db.add(doc_model)
            await db.flush()
            for li in extracted.lines:
                normalized_designation = await word_dictionary.normalize_text(
                    li.designation or "", field_name="designation"
                )
                li_model = LineItem(
                    document_id=doc_model.id,
                    line_number=li.line_number,
                    ref_produit=li.ref_produit,
                    ref_produit_normalized=li.ref_produit_normalized,
                    designation=normalized_designation or li.designation,
                    qty=float(li.qty) if li.qty else None,
                    unit=li.unit,
                    prix_unitaire=float(li.prix_unitaire) if li.prix_unitaire else None,
                    tva_rate=float(li.tva_rate) if li.tva_rate else None,
                    total_ligne_ht=float(li.total_ligne_ht) if li.total_ligne_ht else None,
                    raw_reference=li.raw_reference,
                    raw_designation=li.raw_designation,
                    raw_qty=li.raw_qty,
                    raw_unit_price=li.raw_unit_price,
                    raw_total=li.raw_total,
                    reference_confidence=li.reference_confidence,
                    designation_confidence=li.designation_confidence,
                    quantity_confidence=li.quantity_confidence,
                    unit_price_confidence=li.unit_price_confidence,
                    total_confidence=li.total_confidence,
                    math_consistency_ok=li.math_consistency_ok,
                    field_confidence_map=li.field_confidence_map,
                    extraction_confidence=li.extraction_confidence,
                    has_low_confidence=li.has_low_confidence,
                )
                db.add(li_model)

        await db.commit()
        print()

        # ── Layer 8: Matching ─────────────────────────────────────────
        print("🔗 Layer 8: Matching documents...")
        if "BC" not in extracted_documents:
            print("   ❌ No BC found - cannot proceed\n")
            job.status = JobStatus.FAILED
            job.error_message = "No BC (Purchase Order) found in uploaded document"
            job.processing_completed_at = datetime.now(timezone.utc)
            await _audit(db, job_id, "JOB_FAILED", {
                "error": "No BC (Purchase Order) found in document"
            })
            await db.commit()
            logger.warning("pipeline_no_bc_found job_id=%s", job_id)
            return {"job_id": job_id, "status": "FAILED", "reason": "No BC found"}

        job.status = JobStatus.MATCHING
        await db.commit()

        bc = extracted_documents.get("BC")
        bl = extracted_documents.get("BL")
        facture = extracted_documents.get("FACTURE")
        # Consolidate scheduled delivery BC lines before matching.
        # A commande échelonnée has multiple rows with identical ref+price
        # but different delivery dates. Merge them into one line with summed
        # qty so the matcher compares total ordered against total invoiced.
        if bc and bc.lines:
            from app.utils.fuzzy import normalize_ref as _norm_ref
            from collections import defaultdict
            _grouped: dict[tuple, list] = defaultdict(list)
            _ungrouped = []
            for _line in bc.lines:
                _key = (
                    _norm_ref(_line.ref_produit or ""),
                    str(_line.prix_unitaire or ""),
                )
                if _key[0]:  # only group lines that have a ref
                    _grouped[_key].append(_line)
                else:
                    _ungrouped.append(_line)
            _consolidated = []
            for _key, _lines in _grouped.items():
                if len(_lines) == 1:
                    _consolidated.append(_lines[0])
                else:
                    _merged = _lines[0].model_copy(deep=True)
                    for _extra in _lines[1:]:
                        if _merged.qty is not None and _extra.qty is not None:
                            _merged.qty = _merged.qty + _extra.qty
                    _consolidated.append(_merged)
            bc = bc.model_copy(
                update={"lines": _consolidated + _ungrouped}
            )
        if bc and facture and bc.lines and facture.lines:
            from app.services.normalizer import normalize_reference as _nr  # zid imprt  l fo9 ta3 l app.service.normalizer 
            bc_refs = {_nr(li.ref_produit or "") for li in bc.lines if li.ref_produit}
            fac_refs = {_nr(li.ref_produit or "") for li in facture.lines if li.ref_produit}
            if bc_refs and fac_refs:
                overlap = len(bc_refs & fac_refs) / max(len(bc_refs), len(fac_refs))
                if overlap > 0.50:
                    await _audit(db, job_id, "POSSIBLE_TABLE_REUSE_BUG", {
                        "warning": (
                            "FACTURE refs overlap significantly with BC refs — "
                            "possible extraction error (same table used for both documents)"
                        ),
                        "overlap_ratio": round(overlap, 3),
                        "sample_common_refs": list(bc_refs & fac_refs)[:5],
                    })
                    logger.error(
                        "possible_table_reuse_bug",
                        job_id=job_id,
                        overlap_ratio=round(overlap, 3),
                    )

        date_warnings = validate_date_ordering(bc, bl, facture)
        if date_warnings:
            await _audit(db, job_id, "DATE_ORDER_WARNING", {"warnings": date_warnings})
        supplier_price_tol = None
        supplier_qty_tol = None
        if bl:
            bl_for_profile = bl[0] if isinstance(bl, list) and bl else bl
            bl_supplier_name = getattr(bl_for_profile, "supplier_name", None)
            if bl_supplier_name:
                _bl_profile = await get_supplier_from_text(bl_supplier_name, db)
                if _bl_profile:
                    supplier_price_tol = _bl_profile.price_tolerance
                    supplier_qty_tol = _bl_profile.quantity_tolerance

        alias_scope = (
            supplier_alias_scopes.get("FACTURE")
            or supplier_alias_scopes.get("BL")
            or supplier_alias_scopes.get("BC")
            or {}
        )
        alias_supplier_name = (
            alias_scope.get("supplier_name")
            or getattr(facture, "supplier_name", None)
            or (
                getattr(bl[0], "supplier_name", None)
                if isinstance(bl, list) and bl
                else getattr(bl, "supplier_name", None)
            )
            or getattr(bc, "supplier_name", None)
        )
        reference_aliases = await load_reference_alias_map(
            db,
            supplier_id=alias_scope.get("supplier_id"),
            supplier_code=alias_scope.get("supplier_code"),
            supplier_name=alias_supplier_name,
        )
        if reference_aliases:
            await _audit(db, job_id, "REFERENCE_ALIASES_LOADED", {
                "supplier_id": alias_scope.get("supplier_id"),
                "supplier_code": alias_scope.get("supplier_code"),
                "supplier_name": alias_supplier_name,
                "alias_count": len(reference_aliases),
                "external_refs": sorted(reference_aliases.keys())[:20],
            })

        match_result = await run_three_way_match(
            bc=bc,
            bl=bl,
            facture=facture,
            job_id=job_id,
            supplier_price_tolerance=supplier_price_tol,
            supplier_qty_tolerance=supplier_qty_tol,
            reference_aliases=reference_aliases,
        )
        used_alias_ids = {
            _r.reference_alias_id
            for _r in match_result.line_results
            if _r.reference_alias_id
        }
        await mark_aliases_used(db, used_alias_ids)
        layer_dist: dict[str, int] = {}
        for _r in match_result.line_results:
            _k = f"layer_{_r.match_layer}"
            layer_dist[_k] = layer_dist.get(_k, 0) + 1

        partial_match_count = sum(
            1 for _r in match_result.line_results
            if _r.verdict == "PARTIAL_MATCH"
        )

        print(f"   ✓ Verdict: {match_result.global_verdict}")
        print(f"   Matches: {match_result.match_count}/{match_result.total_lines}")
        if match_result.mismatch_count:
            print(f"   Mismatches: {match_result.mismatch_count}")
        print()
        await _audit(db, job_id, "MATCHING_COMPLETE", {
            "global_verdict": match_result.global_verdict,
            "total_lines": match_result.total_lines,
            "match_count": match_result.match_count,
            "mismatch_count": match_result.mismatch_count,
            "missing_count": match_result.missing_count,
            "extra_count": match_result.extra_count,
            "low_confidence_count": match_result.low_confidence_count,
            "partial_match_count": partial_match_count,
            "match_layer_distribution": layer_dist,
        })

        # ── Layer 9: Save results ─────────────────────────────────────
        mr_model = MatchResult(
            job_id=job_id,
            global_verdict=match_result.global_verdict,
            bc_to_bl_link_confidence=match_result.bc_to_bl_link_confidence,
            bc_to_facture_link_confidence=match_result.bc_to_facture_link_confidence,
            used_fuzzy_link=match_result.used_fuzzy_link,
            total_lines=match_result.total_lines,
            match_count=match_result.match_count,
            mismatch_count=match_result.mismatch_count,
            missing_count=match_result.missing_count,
            extra_count=match_result.extra_count,
            low_confidence_count=match_result.low_confidence_count,
            line_verdicts=[r.model_dump() for r in match_result.line_results],
        )
        db.add(mr_model)
        final_status = (
            JobStatus.REVIEW_REQUIRED
            if match_result.global_verdict in ("REVIEW", "INCOMPLETE")
            else JobStatus.COMPLETED
        )
        job.status = final_status
        job.verdict = JobGlobalVerdict(match_result.global_verdict)
        job.processing_completed_at = datetime.now(timezone.utc)

        await db.commit()

        print(f"{'='*80}")
        print(f"✅ PIPELINE COMPLETE | Status: {final_status.value} | Verdict: {match_result.global_verdict}")
        print(f"{'='*80}\n")

        return {
            "job_id": job_id,
            "status": final_status,
            "verdict": match_result.global_verdict,
        }


# ─── Helpers ───────────────────────────────────────────────────────────────

async def _get_job(db: AsyncSession, job_id: str) -> Job:
    from sqlalchemy import select
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError(f"Job {job_id} not found")
    return job


async def _audit(db: AsyncSession, job_id: str, event_type: str, data: dict):
    """
    Append an immutable audit log entry to the current transaction.

    Uses flush() rather than commit() so the row is visible to the current
    session immediately but does not force a round-trip to PostgreSQL.
    The caller is responsible for committing at natural checkpoints
    (status transitions, layer boundaries).
    The AuditLog table enforces immutability at the DB level via INSERT-only
    privileges — no UPDATE/DELETE is possible regardless of commit timing.
    """
    log = AuditLog(
        job_id=job_id,
        event_type=event_type,
        event_data=data,
        actor="system",
    )
    db.add(log)
    await db.flush() 


async def _mark_job_failed(job_id: str, error: str):
    async with AsyncSessionLocal() as db:
        job = await _get_job(db, job_id)
        job.status = JobStatus.FAILED
        job.error_message = error[:2000]
        job.processing_completed_at = datetime.now(timezone.utc)
        await _audit(db, job_id, "JOB_FAILED", {"error": error})
        await db.commit()


def _get_ref(doc) -> str | None:
    if hasattr(doc, "ref_bc"):
        return doc.ref_bc
    if hasattr(doc, "ref_bl"):
        return doc.ref_bl
    if hasattr(doc, "ref_facture"):
        return doc.ref_facture
    return None


def _extract_context_words(text: str, token: str, window: int = 5) -> list[str]:
    """Return up to `window` words surrounding `token` in `text`."""
    words = text.split()
    try:
        idx = next(i for i, w in enumerate(words) if token.lower() in w.lower())
    except StopIteration:
        return []
    start = max(0, idx - window)
    end = min(len(words), idx + window + 1)
    return [w for w in words[start:end] if w.lower() != token.lower()]


def _select_ocr_text(
    tesseract_text: str,
    tesseract_confidence: float,
    gemini_text: str | None,
) -> tuple[str, str]:
    """
    Choose the OCR text for downstream classification, template extraction,
    and GPT fallback.

    Tesseract remains the source when it is confident because it also gives us
    word boxes for spatial extraction. When Tesseract confidence is low,
    Gemini's plain-text transcription replaces the noisy OCR text.
    """
    tess_text = tesseract_text or ""
    gem_text = (gemini_text or "").strip()

    if gem_text and tesseract_confidence < settings.ocr_confidence_threshold:
        return gem_text, "gemini"

    return tess_text, "tesseract"
