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
                # Ensure X_cal is a DataFrame with feature names (XGBoost requires them)
                if not isinstance(X_cal, pd.DataFrame):
                    X_cal = pd.DataFrame(X_cal, columns=feature_cols)
                elif list(X_cal.columns) != feature_cols:
                    X_cal.columns = feature_cols
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

                # Run LSTM calibration inference in batches to avoid moving
                # the entire calibration tensor to the device at once.
                try:
                    from torch.utils.data import TensorDataset, DataLoader

                    X_np = np.asarray(X_seq_cal, dtype=np.float32)
                    ds = TensorDataset(torch.from_numpy(X_np))
                    loader = DataLoader(
                        ds,
                        batch_size=max(1, int(settings.lstm_batch_size)),
                        shuffle=False,
                        num_workers=0,
                        pin_memory=(device.type == "cuda"),
                    )

                    preds_list = []
                    with torch.no_grad():
                        for (Xb,) in loader:
                            Xb = Xb.to(device)
                            prob, _ = lstm_model(Xb)
                            preds_list.append(prob.squeeze().cpu().numpy())

                    lstm_preds = np.concatenate(preds_list) if preds_list else np.array([])
                except Exception as e:
                    logger.exception("Batched LSTM inference failed, falling back to all-at-once: %s", e)
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

        # Archive to history for performance tracking
        history_dir = model_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        history_path = history_dir / f"training_summary_{timestamp}.json"
        with open(history_path, "w") as f:
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


# ---------------------------------------------------------------------------
# Threshold calibration endpoint
# ---------------------------------------------------------------------------

_calibration_jobs: dict[str, dict] = {}


class CalibrateResponse(BaseModel):
    status: str
    job_id: str
    message: str


class CalibrateStatus(BaseModel):
    job_id: str
    status: str
    thresholds: Optional[dict] = None
    error: Optional[str] = None
    completed_at: Optional[str] = None


def _best_f1_threshold(y_true, y_probs) -> float:
    """Return the probability threshold that maximises F1 on the given data."""
    import numpy as np
    from sklearn.metrics import precision_recall_curve

    precision, recall, thresholds = precision_recall_curve(y_true, y_probs)
    if len(thresholds) == 0:
        return 0.5
    f1 = 2 * precision[:-1] * recall[:-1] / (precision[:-1] + recall[:-1] + 1e-8)
    return float(thresholds[int(f1.argmax())])


async def _run_calibration(job_id: str):
    """Background calibration task: find optimal F1 thresholds on val data and persist them."""
    _calibration_jobs[job_id]["status"] = "running"
    try:
        import numpy as np
        import pandas as pd
        import torch
        from torch.utils.data import TensorDataset, DataLoader

        from app.features.feature_builder import ALL_FEATURES
        from app.features.sequence_builder import build_training_sequences
        from app.models.model_registry import model_registry, CATEGORIES
        from app.config import settings

        parquet_path = Path("training_data") / "training_dataset.parquet"
        if not parquet_path.exists():
            raise RuntimeError("Training dataset not found at training_data/training_dataset.parquet")

        dataset = pd.read_parquet(parquet_path)
        if "date" in dataset.columns:
            dataset = dataset.sort_values("date").reset_index(drop=True)

        feature_cols = [c for c in ALL_FEATURES if c in dataset.columns]
        normalizer = model_registry.get_normalizer()
        model_dir = Path(settings.model_dir)
        thresholds: dict[str, dict] = {}

        for category in CATEGORIES:
            label_col = f"label_{category.lower()}"
            if label_col not in dataset.columns or category not in model_registry.xgboost_models:
                logger.warning(f"Skipping calibration for {category}: missing labels or model")
                continue

            valid_mask = dataset[label_col].notna()
            cat_data = dataset[valid_mask].reset_index(drop=True)
            split_idx = int(len(cat_data) * 0.8)
            val_data = cat_data.iloc[split_idx:].reset_index(drop=True)

            if len(val_data) < 100:
                logger.warning(f"Too few val samples for {category}, skipping")
                continue

            X_val = normalizer.transform(val_data[feature_cols])
            if not isinstance(X_val, pd.DataFrame):
                X_val = pd.DataFrame(X_val, columns=feature_cols)
            y_val = val_data[label_col].astype(int).values

            # XGBoost threshold
            xgb_model = model_registry.xgboost_models[category]
            xgb_probs = xgb_model.predict_proba(X_val)[:, 1]
            xgb_thresh = _best_f1_threshold(y_val, xgb_probs)

            # LSTM + ensemble threshold
            lstm_thresh = None
            ensemble_thresh = None
            if category in model_registry.lstm_models:
                X_seq, y_cls, _ = build_training_sequences(
                    dataset=val_data,
                    feature_cols=feature_cols,
                    label_col=label_col,
                )
                if len(X_seq) >= 50:
                    lstm_model = model_registry.lstm_models[category]
                    lstm_model.eval()
                    device = next(lstm_model.parameters()).device

                    X_np = np.asarray(X_seq, dtype=np.float32)
                    ds = TensorDataset(torch.from_numpy(X_np))
                    dl = DataLoader(ds, batch_size=512, shuffle=False, num_workers=0)
                    preds_list = []
                    with torch.no_grad():
                        for (Xb,) in dl:
                            Xb = Xb.to(device)
                            prob, _ = lstm_model(Xb)
                            preds_list.append(prob.view(-1).cpu().numpy())
                    lstm_probs = np.concatenate(preds_list)
                    y_seq = y_cls[:len(lstm_probs)]
                    lstm_thresh = _best_f1_threshold(y_seq, lstm_probs)

                    # Ensemble threshold (weighted average of XGB + LSTM probs)
                    w = model_registry.ensemble_weights.get(category, {"xgboost": 0.5, "lstm": 0.5})
                    min_len = min(len(xgb_probs), len(lstm_probs))
                    ens_probs = (
                        w["xgboost"] * xgb_probs[-min_len:]
                        + w["lstm"] * lstm_probs[-min_len:]
                    )
                    y_ens = y_val[-min_len:]
                    ensemble_thresh = _best_f1_threshold(y_ens, ens_probs)

            thresholds[category] = {
                "xgboost": round(float(xgb_thresh), 4),
                "lstm": round(float(lstm_thresh), 4) if lstm_thresh is not None else 0.5,
                "ensemble": round(float(ensemble_thresh), 4) if ensemble_thresh is not None else round(float(xgb_thresh), 4),
            }
            logger.info(
                f"Calibrated {category}: "
                f"xgb={thresholds[category]['xgboost']:.3f}  "
                f"lstm={thresholds[category]['lstm']:.3f}  "
                f"ensemble={thresholds[category]['ensemble']:.3f}"
            )

        # Persist calibration thresholds
        calibration_path = model_dir / "calibration.json"
        with open(calibration_path, "w") as f:
            json.dump(
                {"calibrated_at": datetime.utcnow().isoformat(), "thresholds": thresholds},
                f,
                indent=2,
            )

        # Hot-reload into the running registry
        model_registry.calibration_thresholds = thresholds

        _calibration_jobs[job_id]["status"] = "completed"
        _calibration_jobs[job_id]["thresholds"] = thresholds
        logger.info(f"Calibration complete: {list(thresholds.keys())}")

    except Exception as e:
        logger.error(f"Calibration failed: {e}", exc_info=True)
        _calibration_jobs[job_id]["status"] = "failed"
        _calibration_jobs[job_id]["error"] = str(e)

    _calibration_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()


@router.post("/calibrate", response_model=CalibrateResponse)
async def calibrate_thresholds(background_tasks: BackgroundTasks):
    """Sweep decision thresholds on validation data to maximise F1 per model/category."""
    job_id = str(uuid.uuid4())[:8]
    _calibration_jobs[job_id] = {"status": "pending"}
    background_tasks.add_task(_run_calibration, job_id)
    return CalibrateResponse(
        status="started",
        job_id=job_id,
        message="Threshold calibration running in background",
    )


@router.get("/calibrate/{job_id}/status", response_model=CalibrateStatus)
async def get_calibration_status(job_id: str):
    """Check the status of a calibration job."""
    if job_id not in _calibration_jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    job = _calibration_jobs[job_id]
    return CalibrateStatus(
        job_id=job_id,
        status=job.get("status", "unknown"),
        thresholds=job.get("thresholds"),
        error=job.get("error"),
        completed_at=job.get("completed_at"),
    )
