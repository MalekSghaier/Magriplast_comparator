"""
Re-apply word_dictionary corrections to already-saved line items.

When a new entry is added to word_dictionary after a job has been processed,
calling renormalize_saved_job() updates the stored designations without
reprocessing the whole PDF.

Source priority for each line item:
  raw_designation (verbatim OCR) > designation (already-normalised value)
Using raw_designation preserves the original OCR token so the dictionary
lookup is as accurate as possible.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.models.document import Document
from app.models.line_item import LineItem
from app.models.job import Job
from app.services.adaptive_dictionary import word_dictionary

logger = logging.getLogger(__name__)


async def renormalize_saved_job(job_id: str, db: AsyncSession) -> dict:
    """
    Re-apply word_dictionary corrections to all line items of a saved job.

    Returns a report:
      {
        "job_id": ...,
        "lines_scanned": int,
        "lines_modified": int,
        "corrections": [{"line_item_id", "doc_type", "before", "after"}, ...]
      }
    """
    job_result = await db.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    if job is None:
        return {"error": f"Job {job_id!r} not found"}

    docs_result = await db.execute(
        select(Document)
        .where(Document.job_id == job_id)
        .options(selectinload(Document.line_items))
    )
    documents = docs_result.scalars().all()

    lines_scanned = 0
    lines_modified = 0
    corrections: list[dict] = []

    for doc in documents:
        for li in doc.line_items:
            lines_scanned += 1
            # Prefer raw_designation: it keeps the original OCR text so the
            # dictionary lookup sees uncorrected tokens.
            source_text = li.raw_designation or li.designation
            if not source_text:
                continue

            normalized = await word_dictionary.normalize_text(
                source_text, field_name="designation"
            )

            if normalized and normalized != li.designation:
                corrections.append({
                    "line_item_id": li.id,
                    "doc_type": doc.doc_type,
                    "before": li.designation,
                    "after": normalized,
                })
                await db.execute(
                    update(LineItem)
                    .where(LineItem.id == li.id)
                    .values(designation=normalized)
                )
                lines_modified += 1

    await db.commit()

    logger.info(
        "renormalize_complete job_id=%s scanned=%d modified=%d",
        job_id, lines_scanned, lines_modified,
    )
    return {
        "job_id": job_id,
        "lines_scanned": lines_scanned,
        "lines_modified": lines_modified,
        "corrections": corrections,
    }
