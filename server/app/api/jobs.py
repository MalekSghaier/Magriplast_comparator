from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.job import Job
router = APIRouter(tags=["jobs"])


def serialize_job(job: Job) -> dict:
    return {
        "id": job.id,
        "job_id": job.id,
        "status": job.status.value if hasattr(job.status, "value") else job.status,
        "verdict": job.verdict.value if hasattr(job.verdict, "value") else job.verdict,
        "filename": job.original_filename,
        "page_count": job.page_count,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "processing_started_at": (
            job.processing_started_at.isoformat() if job.processing_started_at else None
        ),
        "processing_completed_at": (
            job.processing_completed_at.isoformat() if job.processing_completed_at else None
        ),
        "error": job.error_message,
    }


@router.get("/jobs")
async def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Return recent jobs for sidebar/history views."""
    result = await db.execute(
        select(Job)
        .order_by(Job.created_at.desc())
        .limit(limit)
    )
    return [serialize_job(job) for job in result.scalars().all()]


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    """Poll for job processing status."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return serialize_job(job)
