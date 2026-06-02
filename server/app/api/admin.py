from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from app.core.database import get_db
from app.models.job import Job, JobStatus, GlobalVerdict
from app.models.document import Document, DocumentType
from app.models.match_result import MatchResult
from app.models.audit_log import AuditLog
from app.workers.pipeline import process_document_pipeline
from app.services.renormalize_service import renormalize_saved_job
from app.services.reference_aliases import (
    approve_reference_alias,
    choose_supplier_alias_key,
)
from app.utils.fuzzy import normalize_ref
from app.core.storage import storage_client
from app.models.line_item import LineItem
from app.schemas.documents import BonDeCommandeSchema, BonDeLivraison, FactureSchema, LineItemSchema
from app.services.matcher import run_three_way_match
from app.services.reference_aliases import load_reference_alias_map
from app.workers.pipeline import _get_job as _get_job_from_pipeline, _audit as _audit_from_pipeline
from fastapi.responses import StreamingResponse
from botocore.exceptions import ClientError
import io
router = APIRouter(tags=["admin"])


class ReviewDecision(BaseModel):
    reviewer_id: str
    approved: bool
    notes: Optional[str] = None
    corrected_doc_type: Optional[str] = None  # For page re-classification


class ReferenceAliasApproval(BaseModel):
    reviewer_id: str
    external_ref: str
    internal_ref: str
    supplier_name: Optional[str] = None
    notes: Optional[str] = None


@router.patch("/jobs/{job_id}/review")
async def submit_review(
    job_id: str,
    decision: ReviewDecision,
    db: AsyncSession = Depends(get_db),
):
    """
    Human review endpoint.
    Called by accounting team to approve/reject a flagged job.
    All decisions are written to the immutable audit log.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if job.status not in (JobStatus.REVIEW_REQUIRED, JobStatus.FAILED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job status is {job.status} — review not applicable",
        )

    audit_entry = AuditLog(
        job_id=job_id,
        event_type="HUMAN_REVIEW_COMPLETED",
        event_data={
            "reviewer_id": decision.reviewer_id,
            "approved": decision.approved,
            "notes": decision.notes,
            "corrected_doc_type": decision.corrected_doc_type,
            "previous_status": job.status,
            "previous_verdict": job.verdict,
        },
        actor=decision.reviewer_id,
    )
    db.add(audit_entry)
    if decision.approved:
        job.status = JobStatus.COMPLETED
        job.verdict = GlobalVerdict.VALIDATED
    else:
        job.status = JobStatus.FAILED
        job.verdict = GlobalVerdict.REJECTED

    await db.commit()

    return {
        "job_id": job_id,
        "new_status": job.status,
        "new_verdict": job.verdict,
        "reviewed_by": decision.reviewer_id,
        "message": "Review decision recorded",
    }


def _alias_payload_matches_line(line: dict, external_ref: str, internal_ref: str) -> bool:
    external_norm = normalize_ref(external_ref)
    internal_norm = normalize_ref(internal_ref)
    line_external = line.get("ref_produit_facture") or line.get("ref_produit_bl")
    return (
        normalize_ref(line.get("ref_produit") or "") == internal_norm
        and normalize_ref(line_external or "") == external_norm
    )


def _line_is_safe_alias_candidate(line: dict) -> bool:
    if line.get("verdict") not in {"LOW_CONFIDENCE", "PARTIAL_MATCH", "MATCH"}:
        return False
    if line.get("mismatch_fields"):
        return False
    if not (line.get("ref_produit") and (line.get("ref_produit_facture") or line.get("ref_produit_bl"))):
        return False
    if line.get("ref_produit_facture"):
        qty_bc = line.get("qty_bc")
        qty_facture = line.get("qty_facture")
        price_bc = line.get("prix_bc")
        price_facture = line.get("prix_facture")
        if qty_bc is None or qty_facture is None or float(qty_bc) != float(qty_facture):
            return False
        if price_bc is None or price_facture is None:
            return False
        return abs(float(price_bc) - float(price_facture)) <= 0.100

    return line.get("qty_bc") is not None and line.get("qty_bl") is not None


@router.post("/jobs/{job_id}/reference-aliases", status_code=status.HTTP_201_CREATED)
async def approve_job_reference_alias(
    job_id: str,
    approval: ReferenceAliasApproval,
    db: AsyncSession = Depends(get_db),
):
    """
    Approve a supplier-specific reference alias from a human review.

    The alias is used only for future matching; extracted document references
    remain unchanged for auditability.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    match_result = (
        await db.execute(select(MatchResult).where(MatchResult.job_id == job_id))
    ).scalar_one_or_none()
    if not match_result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job has no match result to approve aliases from",
        )

    source_line = None
    for line in match_result.line_verdicts or []:
        if _alias_payload_matches_line(line, approval.external_ref, approval.internal_ref):
            source_line = line
            break

    if source_line is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No comparison line matches the requested alias pair",
        )
    if not _line_is_safe_alias_candidate(source_line):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Alias approval is allowed only for safe reference-only matches "
                "with no price, quantity, or TVA mismatch"
            ),
        )

    docs = (
        await db.execute(select(Document).where(Document.job_id == job_id))
    ).scalars().all()
    supplier_doc = next(
        (doc for doc in docs if doc.doc_type == DocumentType.FACTURE),
        None,
    ) or next((doc for doc in docs if doc.doc_type == DocumentType.BL), None)

    supplier_name = (
        approval.supplier_name
        or (supplier_doc.supplier_name_raw if supplier_doc else None)
    )
    supplier_id = supplier_doc.supplier_id if supplier_doc else None
    supplier_key = choose_supplier_alias_key(
        supplier_id=supplier_id,
        supplier_name=supplier_name,
    )
    if not supplier_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot approve alias without a supplier identity",
        )

    try:
        alias, created = await approve_reference_alias(
            db,
            supplier_id=supplier_id,
            supplier_key=supplier_key,
            supplier_name=supplier_name,
            external_ref=approval.external_ref,
            internal_ref=approval.internal_ref,
            approved_by=approval.reviewer_id,
            source_job_id=job_id,
            source_line=source_line,
            description=source_line.get("designation"),
            notes=approval.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.add(AuditLog(
        job_id=job_id,
        event_type="REFERENCE_ALIAS_APPROVED",
        event_data={
            "alias_id": alias.id,
            "created": created,
            "supplier_key": supplier_key,
            "supplier_name": supplier_name,
            "external_ref": approval.external_ref,
            "internal_ref": approval.internal_ref,
            "source_verdict": source_line.get("verdict"),
        },
        actor=approval.reviewer_id,
    ))
    await db.commit()
    await db.refresh(alias)

    return {
        "id": alias.id,
        "created": created,
        "supplier_key": alias.supplier_key,
        "supplier_name": alias.supplier_name,
        "external_ref": alias.external_ref,
        "internal_ref": alias.internal_ref,
        "message": "Reference alias approved",
    }


@router.post("/jobs/{job_id}/renormalize")
async def renormalize_job_designations(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Re-apply word_dictionary corrections to all line items of a saved job.

    Use this after adding new entries to word_dictionary to update already-processed
    documents without reprocessing the PDF.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    report = await renormalize_saved_job(job_id, db)
    return report


@router.get("/jobs/{job_id}/audit")
async def get_audit_trail(job_id: str, db: AsyncSession = Depends(get_db)):
    """Return the full immutable audit log for a job."""
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.job_id == job_id)
        .order_by(AuditLog.created_at.asc())
    )
    logs = result.scalars().all()

    if not logs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No audit logs found")

    return {
        "job_id": job_id,
        "audit_trail": [
            {
                "event_type": log.event_type,
                "actor": log.actor,
                "timestamp": log.created_at.isoformat(),
                "data": log.event_data,
            }
            for log in logs
        ],
    }


@router.get("/jobs/{job_id}/pdf-url")
async def get_pdf_url(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Return the same-origin proxy URL for the PDF.
    The frontend iframe always uses /api/v1/jobs/{id}/pdf — never a raw
    MinIO/S3 URL — so it works in every environment without CORS or
    signed-URL lifetime issues.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not getattr(job, "original_pdf_key", None):
        raise HTTPException(status_code=404, detail="No original PDF available for this job")

    # Always return a relative path — the frontend resolves it against the
    # API base URL set in the axios client, so it works in dev (Vite proxy)
    # and in prod (same-origin or behind a reverse proxy).
    return {"url": f"/api/v1/jobs/{job_id}/pdf"}


@router.get("/jobs/{job_id}/pdf")
async def stream_job_pdf(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Stream the original PDF through the FastAPI server.

    The server fetches the file from MinIO/S3 using the *internal* endpoint
    URL (e.g. http://minio:9000 in Docker, http://localhost:9000 in dev).
    The browser only ever talks to the FastAPI server — no direct MinIO
    connection, no cross-origin issues, no signed-URL expiry.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not getattr(job, "original_pdf_key", None):
        raise HTTPException(status_code=404, detail="No original PDF available for this job")

    try:
        stream = storage_client.stream_object(job.original_pdf_key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "Unknown")
        if error_code in ("NoSuchKey", "404"):
            raise HTTPException(status_code=404, detail="PDF not found in storage")
        raise HTTPException(
            status_code=502,
            detail=f"Storage error ({error_code}): could not retrieve PDF. "
                   f"Check that STORAGE_ENDPOINT_URL is reachable from the server "
                   f"(current value: see server .env / STORAGE_ENDPOINT_URL).",
        ) from exc

    headers = {
        "Content-Disposition": f'inline; filename="{job_id}.pdf"',
        # Allow the iframe (same origin via proxy) to display the PDF
        "X-Frame-Options": "SAMEORIGIN",
        "Cache-Control": "private, max-age=300",
    }
    return StreamingResponse(stream, media_type="application/pdf", headers=headers)


@router.patch("/jobs/{job_id}/documents/{document_id}")
async def patch_document_header(job_id: str, document_id: str, body: dict, db: AsyncSession = Depends(get_db)):
    """
    Patch top-level document header fields corrected by a human.
    """
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc or doc.job_id != job_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found for job")
    fields = {}
    field_map = (
        ("ref_document", "ref_document"),
        ("document_date", "document_date"),
        ("supplier_name", "supplier_name_raw"),
        ("total_ht", "total_ht"),
        ("total_ttc", "total_ttc"),
    )
    for api_field, model_field in field_map:
        if api_field in body and body[api_field] is not None:
            val = body[api_field]
            if api_field == "document_date":
                # accept ISO date string
                try:
                    from datetime import date

                    if isinstance(val, str):
                        val = date.fromisoformat(val)
                except Exception:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid document_date format")
            setattr(doc, model_field, val)
            fields[api_field] = body[api_field]

    db.add(AuditLog(
        job_id=job_id,
        event_type="DOCUMENT_HEADER_EDITED_BY_HUMAN",
        event_data={"document_id": document_id, "fields": fields},
        actor=body.get("reviewer_id") or "human",
    ))

    await db.commit()
    return {"ok": True}


@router.patch("/jobs/{job_id}/documents/{document_id}/lines")
async def patch_document_lines(job_id: str, document_id: str, body: dict, db: AsyncSession = Depends(get_db)):
    """
    Patch existing line items or add new ones from human edits.
    """
    edits = body.get("edits", []) or []
    edit_count = 0
    for edit in edits:
        if edit.get("line_id"):
            result = await db.execute(select(LineItem).where(LineItem.id == edit["line_id"]))
            line = result.scalar_one_or_none()
            if line and line.document_id == document_id:
                for f in ("ref_produit", "designation", "qty", "prix_unitaire", "tva_rate", "total_ligne_ht"):
                    if f in edit:
                        setattr(line, f, edit[f])
                edit_count += 1
        else:
            data = {f: edit.get(f) for f in ("ref_produit", "designation", "qty", "prix_unitaire", "tva_rate", "total_ligne_ht")}
            new_line = LineItem(document_id=document_id, line_number=edit.get("line_number", 0), **data)
            db.add(new_line)
            edit_count += 1

    db.add(AuditLog(
        job_id=job_id,
        event_type="DOCUMENT_LINES_EDITED_BY_HUMAN",
        event_data={"document_id": document_id, "edit_count": edit_count},
        actor=body.get("reviewer_id") or "human",
    ))
    await db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/rematch")
async def rematch(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Re-run the three-way matcher using the current (possibly human-edited)
    extracted data and overwrite the MatchResult row.
    """
    # ensure job exists
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    docs = (await db.execute(select(Document).where(Document.job_id == job_id))).scalars().all()
    if not docs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No documents for job")

    bc = None
    bl_list: list[BonDeLivraison] = []
    facture = None

    for doc in docs:
        raw = doc.raw_extracted_data or {}
        try:
            if doc.doc_type.name == "BC":
                bc = BonDeCommandeSchema.model_validate(raw) if raw else None
            elif doc.doc_type.name == "BL":
                bl_list.append(BonDeLivraison.model_validate(raw) if raw else None)
            elif doc.doc_type.name == "FACTURE":
                facture = FactureSchema.model_validate(raw) if raw else None
        except Exception:
            # fallback: build minimal schema from DB rows
            lines = []
            for li in doc.line_items:
                lines.append(LineItemSchema(
                    line_number=li.line_number,
                    ref_produit=li.ref_produit,
                    ref_produit_normalized=li.ref_produit_normalized,
                    designation=li.designation,
                    qty=li.qty,
                    prix_unitaire=li.prix_unitaire,
                    tva_rate=li.tva_rate,
                    total_ligne_ht=li.total_ligne_ht,
                ))
            if doc.doc_type.name == "BC":
                bc = BonDeCommandeSchema(ref_bc=doc.ref_document or "", document_date=doc.document_date, supplier_name=doc.supplier_name_raw, lines=lines)
            elif doc.doc_type.name == "BL":
                bl_list.append(BonDeLivraison(ref_bl=doc.ref_document or "", document_date=doc.document_date, supplier_name=doc.supplier_name_raw, lines=lines))
            elif doc.doc_type.name == "FACTURE":
                facture = FactureSchema(ref_facture=doc.ref_document or "", document_date=doc.document_date, supplier_name=doc.supplier_name_raw, lines=lines, total_ht=doc.total_ht, total_ttc=doc.total_ttc, tva_rate=doc.tva_rate)

    if bc is None and facture is None and not bl_list:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid extracted documents to rematch")

    # load reference aliases scoped to supplier from facture (if present) or first doc
    supplier_id = None
    supplier_name = None
    for d in docs:
        if d.supplier_id:
            supplier_id = d.supplier_id
            supplier_name = d.supplier_name_raw
            break

    reference_aliases = await load_reference_alias_map(db, supplier_id=supplier_id, supplier_name=supplier_name)

    match_result = await run_three_way_match(
        bc=bc if bc else BonDeCommandeSchema(ref_bc="", lines=[]),
        bl=bl_list if bl_list else None,
        facture=facture if facture else None,
        job_id=job_id,
        reference_aliases=reference_aliases,
    )
    existing = (await db.execute(select(MatchResult).where(MatchResult.job_id == job_id))).scalar_one_or_none()
    if existing:
        existing.global_verdict = match_result.global_verdict
        existing.bc_to_bl_link_confidence = match_result.bc_to_bl_link_confidence
        existing.bc_to_facture_link_confidence = match_result.bc_to_facture_link_confidence
        existing.used_fuzzy_link = match_result.used_fuzzy_link
        existing.total_lines = match_result.total_lines
        existing.match_count = match_result.match_count
        existing.mismatch_count = match_result.mismatch_count
        existing.missing_count = match_result.missing_count
        existing.extra_count = match_result.extra_count
        existing.low_confidence_count = match_result.low_confidence_count
        existing.line_verdicts = [r.model_dump() for r in match_result.line_results]
    else:
        mr = MatchResult(
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
        db.add(mr)

    await _audit_from_pipeline(db, job_id, "HUMAN_TRIGGERED_REMATCH", {"match_count": match_result.match_count, "mismatch_count": match_result.mismatch_count, "global_verdict": match_result.global_verdict})
    await db.commit()

    return {"ok": True}
