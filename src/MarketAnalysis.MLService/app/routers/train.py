import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
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
        import pandas as pd
        from app.models.xgboost_model import XGBoostScorer
        from app.models.model_registry import model_registry
        from app.features.feature_builder import ALL_FEATURES
        from app.features.normalizer import FeatureNormalizer
        from app.config import settings

        model_dir = Path(settings.model_dir)
        model_dir.mkdir(parents=True, exist_ok=True)

        parquet_path = Path("training_data") / "training_dataset.parquet"
        if not parquet_path.exists():
            raise RuntimeError(
                f"Training dataset not found at {parquet_path}. Run backfill first."
            )

        dataset = pd.read_parquet(parquet_path)
        logger.info(f"Loaded training dataset: {len(dataset)} rows, {len(dataset.columns)} columns")

        # Ensure dataset is sorted by date for time-ordered splits
        if "date" in dataset.columns:
            dataset = dataset.sort_values("date").reset_index(drop=True)

        # Extract feature columns present in the dataset
        feature_cols = [c for c in ALL_FEATURES if c in dataset.columns]
        if not feature_cols:
            raise RuntimeError("No feature columns found in training dataset")

        logger.info(f"Using {len(feature_cols)} features for training")

        # Fit normalizer on all feature data and save it
        normalizer = FeatureNormalizer()
        all_features_df = dataset[feature_cols]
        normalizer.fit(all_features_df)
        normalizer_path = model_dir / "normalizer.json"
        normalizer.save(normalizer_path)
        logger.info(f"Fitted and saved normalizer with {len(feature_cols)} features")

        # Normalize the training features
        X_normalized = normalizer.transform(all_features_df)

        if "xgboost" in models:
            logger.info("Training XGBoost models...")

            for category in categories:
                if category not in CATEGORIES:
                    continue

                label_col = f"label_{category.lower()}"
                if label_col not in dataset.columns:
                    logger.warning(f"No labels for {category}, skipping")
                    continue

                # Drop rows without labels
                valid_mask = dataset[label_col].notna()
                X = X_normalized[valid_mask].reset_index(drop=True)
                y = dataset.loc[valid_mask, label_col].astype(int).reset_index(drop=True)

                if len(X) < 100:
                    logger.warning(f"Too few samples for {category} ({len(X)}), skipping")
                    continue

                scorer = XGBoostScorer(category)
                cat_metrics = scorer.train(X, y)
                metrics[f"xgboost_{category.lower()}"] = cat_metrics

                # Save model
                model_path = model_dir / f"xgboost_{category.lower()}.json"
                scorer.save(model_path)

                # Save metadata (metrics, feature importance)
                meta_path = model_dir / f"xgboost_{category.lower()}_metadata.json"
                scorer.save_metadata(meta_path)

                # Register in model_registry for immediate use
                model_registry.xgboost_models[category] = scorer.model

                logger.info(
                    f"Trained {category}: AUC={cat_metrics['auc']:.3f}, "
                    f"CV_AUC={cat_metrics['cv_auc_mean']:.3f}"
                )

        # LSTM and ensemble training follow same pattern
        # (implemented in Phase 4 and Phase 5)
        if "lstm" in models:
            logger.info("LSTM training not yet implemented (Phase 4)")
            metrics["lstm"] = {"status": "not_implemented"}

        if "ensemble" in models:
            logger.info("Ensemble calibration not yet implemented (Phase 5)")
            metrics["ensemble"] = {"status": "not_implemented"}

        # Save overall training summary
        summary = {
            "trained_at": datetime.utcnow().isoformat(),
            "dataset_rows": len(dataset),
            "feature_count": len(feature_cols),
            "categories_trained": [
                c for c in categories
                if f"xgboost_{c.lower()}" in metrics
            ],
            "metrics": metrics,
        }
        summary_path = model_dir / "training_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)

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
