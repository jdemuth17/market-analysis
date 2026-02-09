import logging
import uuid
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

_backfill_jobs: dict[str, dict] = {}


class BackfillRequest(BaseModel):
    start_date: str = "2022-01-01"
    phases: list[str] = ["prices", "technicals", "fundamentals", "labels"]


class BackfillResponse(BaseModel):
    status: str
    job_id: str
    message: str


class BackfillStatus(BaseModel):
    job_id: str
    status: str
    phase: Optional[str] = None
    progress: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


async def _run_backfill(job_id: str, start_date: str, phases: list[str]):
    """Background backfill task."""
    _backfill_jobs[job_id]["status"] = "running"
    _backfill_jobs[job_id]["started_at"] = datetime.utcnow().isoformat()

    try:
        if "prices" in phases:
            _backfill_jobs[job_id]["phase"] = "prices"
            logger.info("Phase 1: Price backfill starting...")
            from app.backfill.price_backfill import run_price_backfill
            await run_price_backfill(start_date)
            logger.info("Phase 1: Price backfill complete")

        if "technicals" in phases:
            _backfill_jobs[job_id]["phase"] = "technicals"
            logger.info("Phase 2: Technical backfill starting...")
            from app.backfill.technical_backfill import run_technical_backfill
            await run_technical_backfill(start_date)
            logger.info("Phase 2: Technical backfill complete")

        if "fundamentals" in phases:
            _backfill_jobs[job_id]["phase"] = "fundamentals"
            logger.info("Phase 3: Fundamental backfill starting...")
            from app.backfill.fundamental_backfill import run_fundamental_backfill
            await run_fundamental_backfill(start_date)
            logger.info("Phase 3: Fundamental backfill complete")

        if "labels" in phases:
            _backfill_jobs[job_id]["phase"] = "labels"
            logger.info("Phase 5: Label generation starting...")
            from app.backfill.label_generator import run_label_generation
            await run_label_generation()
            logger.info("Phase 5: Label generation complete")

        _backfill_jobs[job_id]["status"] = "completed"

    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        _backfill_jobs[job_id]["status"] = "failed"
        _backfill_jobs[job_id]["error"] = str(e)

    _backfill_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()


@router.post("/backfill", response_model=BackfillResponse)
async def start_backfill(
    request: BackfillRequest,
    background_tasks: BackgroundTasks,
):
    """Trigger data backfill as a background job."""
    job_id = str(uuid.uuid4())[:8]

    _backfill_jobs[job_id] = {
        "status": "pending",
        "phases": request.phases,
    }

    background_tasks.add_task(_run_backfill, job_id, request.start_date, request.phases)

    return BackfillResponse(
        status="started",
        job_id=job_id,
        message=f"Backfill started for phases: {request.phases}",
    )


@router.get("/backfill/{job_id}/status", response_model=BackfillStatus)
async def get_backfill_status(job_id: str):
    """Check the status of a backfill job."""
    if job_id not in _backfill_jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job = _backfill_jobs[job_id]
    return BackfillStatus(
        job_id=job_id,
        status=job.get("status", "unknown"),
        phase=job.get("phase"),
        progress=job.get("progress"),
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        error=job.get("error"),
    )
