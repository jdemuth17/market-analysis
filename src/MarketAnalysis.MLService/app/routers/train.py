import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.models.model_registry import CATEGORIES

logger = logging.getLogger(__name__)
router = APIRouter()

# Simple in-memory job tracking
_training_jobs: dict[str, dict] = {}


class TrainRequest(BaseModel):
    models: list[str] = ["xgboost", "lstm", "ensemble"]
    categories: list[str] = CATEGORIES


class TrainResponse(BaseModel):
    status: str
    job_id: str
    message: str


class TrainStatus(BaseModel):
    job_id: str
    status: str  # pending, running, completed, failed
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metrics: Optional[dict] = None
    error: Optional[str] = None


async def _run_training(job_id: str, models: list[str], categories: list[str]):
    """Background training task."""
    _training_jobs[job_id]["status"] = "running"
    _training_jobs[job_id]["started_at"] = datetime.utcnow().isoformat()
    metrics = {}

    try:
        from app.db.connection import async_session
        from app.features.feature_builder import FeatureBuilder
        from app.db.queries import get_active_stocks
        from app.models.xgboost_model import XGBoostScorer
        from app.models.model_registry import model_registry
        from app.config import settings
        from pathlib import Path
        import pandas as pd

        async with async_session() as session:
            builder = FeatureBuilder(session)

            if "xgboost" in models:
                logger.info("Training XGBoost models...")
                # Build feature matrix from all stocks with sufficient data
                dataset = await builder.build_training_dataset(session)
                if dataset is None or dataset.empty:
                    raise RuntimeError("No training data available. Run backfill first.")

                for category in categories:
                    if category not in CATEGORIES:
                        continue

                    label_col = f"label_{category.lower()}"
                    if label_col not in dataset.columns:
                        logger.warning(f"No labels for {category}, skipping")
                        continue

                    # Drop rows without labels
                    cat_data = dataset.dropna(subset=[label_col])
                    feature_cols = [c for c in cat_data.columns if not c.startswith("label_")]
                    X = cat_data[feature_cols]
                    y = cat_data[label_col].astype(int)

                    scorer = XGBoostScorer(category)
                    cat_metrics = scorer.train(X, y)
                    metrics[f"xgboost_{category.lower()}"] = cat_metrics

                    # Save model
                    model_path = Path(settings.model_dir) / f"xgboost_{category.lower()}.json"
                    scorer.save(model_path)
                    model_registry.xgboost_models[category] = scorer.model

            # LSTM and ensemble training follow same pattern
            # (implemented in Phase 4 and Phase 5)
            if "lstm" in models:
                logger.info("LSTM training not yet implemented (Phase 4)")
                metrics["lstm"] = {"status": "not_implemented"}

            if "ensemble" in models:
                logger.info("Ensemble calibration not yet implemented (Phase 5)")
                metrics["ensemble"] = {"status": "not_implemented"}

        _training_jobs[job_id]["status"] = "completed"
        _training_jobs[job_id]["metrics"] = metrics

    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        _training_jobs[job_id]["status"] = "failed"
        _training_jobs[job_id]["error"] = str(e)

    _training_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()


@router.post("/train", response_model=TrainResponse)
async def start_training(
    request: TrainRequest,
    background_tasks: BackgroundTasks,
):
    """Trigger model training as a background job."""
    job_id = str(uuid.uuid4())[:8]

    _training_jobs[job_id] = {
        "status": "pending",
        "models": request.models,
        "categories": request.categories,
    }

    background_tasks.add_task(_run_training, job_id, request.models, request.categories)

    return TrainResponse(
        status="started",
        job_id=job_id,
        message=f"Training {request.models} for {request.categories}",
    )


@router.get("/train/{job_id}/status", response_model=TrainStatus)
async def get_training_status(job_id: str):
    """Check the status of a training job."""
    if job_id not in _training_jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job = _training_jobs[job_id]
    return TrainStatus(
        job_id=job_id,
        status=job.get("status", "unknown"),
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        metrics=job.get("metrics"),
        error=job.get("error"),
    )
