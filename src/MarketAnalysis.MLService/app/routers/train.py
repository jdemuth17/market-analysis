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

        # LSTM training: build per-stock sequences, train 4 models
        if "lstm" in models:
            logger.info("Training LSTM models...")
            from app.models.lstm_trainer import LSTMTrainer
            from app.features.sequence_builder import build_training_sequences

            # Map category to its return column for regression head
            return_col_map = {
                "DayTrade": "return_1d",
                "SwingTrade": "return_5d",
                "ShortTermHold": "return_10d",
                "LongTermHold": "return_30d",
            }

            for category in categories:
                if category not in CATEGORIES:
                    continue

                label_col = f"label_{category.lower()}"
                return_col = return_col_map.get(category)

                if label_col not in dataset.columns:
                    logger.warning(f"No labels for LSTM {category}, skipping")
                    continue

                # Build per-stock sequences (no cross-stock contamination)
                X_seq, y_cls, y_reg = build_training_sequences(
                    dataset=dataset,
                    feature_cols=feature_cols,
                    label_col=label_col,
                    return_col=return_col,
                )

                if len(X_seq) < 100:
                    logger.warning(f"Too few LSTM sequences for {category} ({len(X_seq)}), skipping")
                    continue

                # Time-ordered split: 80% train, 20% val
                split_idx = int(len(X_seq) * 0.8)
                X_train_seq = X_seq[:split_idx]
                y_cls_train = y_cls[:split_idx]
                y_reg_train = y_reg[:split_idx] if y_reg is not None else None
                X_val_seq = X_seq[split_idx:]
                y_cls_val = y_cls[split_idx:]
                y_reg_val = y_reg[split_idx:] if y_reg is not None else None

                trainer = LSTMTrainer(category)
                cat_metrics = trainer.train(
                    X_train_seq, y_cls_train, y_reg_train,
                    X_val_seq, y_cls_val, y_reg_val,
                )
                metrics[f"lstm_{category.lower()}"] = cat_metrics

                # Save model and metadata
                lstm_path = model_dir / f"lstm_{category.lower()}.pt"
                trainer.save(lstm_path)

                lstm_meta_path = model_dir / f"lstm_{category.lower()}_metadata.json"
                trainer.save_metadata(lstm_meta_path)

                # Register for immediate use
                model_registry.lstm_models[category] = trainer.model

                logger.info(
                    f"LSTM {category}: AUC={cat_metrics['auc']:.3f}, "
                    f"epochs={cat_metrics['total_epochs']}, "
                    f"time={cat_metrics['training_time_sec']}s"
                )

        # Ensemble calibration: learn optimal XGBoost/LSTM weights per category
        if "ensemble" in models:
            logger.info("Calibrating ensemble weights...")
            import numpy as np
            import torch
            from app.models.ensemble import EnsembleScorer

            ensemble_scorer = EnsembleScorer()
            ensemble_metrics = {}

            for category in categories:
                if category not in CATEGORIES:
                    continue

                has_xgb = category in model_registry.xgboost_models
                has_lstm = category in model_registry.lstm_models

                if not (has_xgb and has_lstm):
                    logger.info(f"Ensemble {category}: skipping (need both XGBoost + LSTM)")
                    continue

                label_col = f"label_{category.lower()}"
                if label_col not in dataset.columns:
                    continue

                # Use the last 20% of data as calibration set (same as val split)
                valid_mask = dataset[label_col].notna()
                cal_data = dataset[valid_mask].reset_index(drop=True)
                split_idx = int(len(cal_data) * 0.8)
                cal_set = cal_data.iloc[split_idx:]

                if len(cal_set) < 50:
                    logger.warning(f"Too few calibration samples for {category}")
                    continue

                # XGBoost predictions on calibration set
                X_cal = normalizer.transform(cal_set[feature_cols])
                xgb_model = model_registry.xgboost_models[category]
                xgb_preds = xgb_model.predict_proba(X_cal)[:, 1]

                # LSTM predictions on calibration set (build sequences per-stock)
                from app.features.sequence_builder import build_training_sequences
                X_seq_cal, y_cls_cal, _ = build_training_sequences(
                    dataset=cal_set,
                    feature_cols=feature_cols,
                    label_col=label_col,
                )

                if len(X_seq_cal) < 50:
                    logger.warning(f"Too few LSTM calibration sequences for {category}")
                    continue

                lstm_model = model_registry.lstm_models[category]
                lstm_model.eval()
                device = next(lstm_model.parameters()).device
                with torch.no_grad():
                    tensor = torch.FloatTensor(X_seq_cal).to(device)
                    prob, _ = lstm_model(tensor)
                    lstm_preds = prob.squeeze().cpu().numpy()

                # Align lengths (LSTM sequences may be shorter)
                min_len = min(len(xgb_preds), len(lstm_preds), len(y_cls_cal))
                xgb_cal = xgb_preds[-min_len:]
                lstm_cal = lstm_preds[-min_len:]
                y_cal = y_cls_cal[-min_len:].astype(int)

                weights = ensemble_scorer.calibrate(category, xgb_cal, lstm_cal, y_cal)
                ensemble_metrics[category] = weights

            if ensemble_scorer.weights:
                weights_path = model_dir / "ensemble_weights.json"
                ensemble_scorer.save(weights_path)
                model_registry.ensemble_weights = ensemble_scorer.weights
                metrics["ensemble"] = ensemble_metrics
                logger.info(f"Ensemble calibrated for {list(ensemble_scorer.weights.keys())}")
            else:
                metrics["ensemble"] = {"status": "no_categories_calibrated"}

        # Save overall training summary
        summary = {
            "trained_at": datetime.utcnow().isoformat(),
            "dataset_rows": len(dataset),
            "feature_count": len(feature_cols),
            "xgboost_categories": [
                c for c in categories
                if f"xgboost_{c.lower()}" in metrics
            ],
            "lstm_categories": [
                c for c in categories
                if f"lstm_{c.lower()}" in metrics
            ],
            "ensemble_categories": list(model_registry.ensemble_weights.keys()),
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
