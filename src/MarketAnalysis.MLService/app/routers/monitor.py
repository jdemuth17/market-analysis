"""
Model monitoring, drift detection, and performance tracking endpoints.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.models.model_registry import model_registry, CATEGORIES

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory prediction log for drift detection
_prediction_log: list[dict] = []
MAX_LOG_SIZE = 10000


def log_prediction(category: str, score: float, features: dict):
    """Called by predict endpoint to track prediction distribution."""
    _prediction_log.append({
        "timestamp": datetime.utcnow().isoformat(),
        "category": category,
        "score": score,
        "feature_sample": {k: v for k, v in list(features.items())[:5]},
    })
    if len(_prediction_log) > MAX_LOG_SIZE:
        _prediction_log.pop(0)


class DriftAlert(BaseModel):
    category: str
    metric: str
    message: str
    severity: str  # info, warning, critical


class MonitorResponse(BaseModel):
    status: str
    models_loaded: dict
    prediction_stats: dict
    drift_alerts: list[DriftAlert]
    last_trained: Optional[str] = None


@router.get("/monitor", response_model=MonitorResponse)
async def get_monitoring_status():
    """Comprehensive monitoring: model status, prediction stats, drift alerts."""
    alerts: list[DriftAlert] = []
    model_status = model_registry.get_status()

    # Prediction distribution stats
    pred_stats = {}
    for category in CATEGORIES:
        cat_preds = [p for p in _prediction_log if p["category"] == category]
        if cat_preds:
            scores = [p["score"] for p in cat_preds]
            pred_stats[category] = {
                "count": len(scores),
                "mean": round(float(np.mean(scores)), 3),
                "std": round(float(np.std(scores)), 3),
                "min": round(float(np.min(scores)), 3),
                "max": round(float(np.max(scores)), 3),
                "pct_above_50": round(sum(1 for s in scores if s > 50) / len(scores) * 100, 1),
            }

            # Drift detection: check for distribution anomalies
            if np.std(scores) < 0.01:
                alerts.append(DriftAlert(
                    category=category,
                    metric="score_variance",
                    message=f"Prediction scores have near-zero variance ({np.std(scores):.4f}). Model may be collapsed.",
                    severity="critical",
                ))
            if np.mean(scores) > 90 or np.mean(scores) < 10:
                alerts.append(DriftAlert(
                    category=category,
                    metric="score_mean",
                    message=f"Mean prediction score is extreme ({np.mean(scores):.1f}). Possible distribution shift.",
                    severity="warning",
                ))
        else:
            pred_stats[category] = {"count": 0}

    # Check model staleness
    trained_at = model_registry.get_training_date()
    if trained_at:
        try:
            trained_dt = datetime.fromisoformat(trained_at)
            days_since = (datetime.utcnow() - trained_dt).days
            if days_since > 14:
                alerts.append(DriftAlert(
                    category="all",
                    metric="model_age",
                    message=f"Models are {days_since} days old. Consider retraining.",
                    severity="warning" if days_since < 30 else "critical",
                ))
        except (ValueError, TypeError):
            pass

    # Check for missing models
    for category in CATEGORIES:
        if category not in model_registry.xgboost_models:
            alerts.append(DriftAlert(
                category=category,
                metric="model_missing",
                message=f"No XGBoost model loaded for {category}.",
                severity="critical",
            ))

    return MonitorResponse(
        status="healthy" if not any(a.severity == "critical" for a in alerts) else "degraded",
        models_loaded=model_status,
        prediction_stats=pred_stats,
        drift_alerts=alerts,
        last_trained=trained_at,
    )


class PerformanceEntry(BaseModel):
    category: str
    model_type: str
    auc: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1: Optional[float] = None
    trained_at: Optional[str] = None


class PerformanceResponse(BaseModel):
    entries: list[PerformanceEntry]
    training_summary: Optional[dict] = None


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance():
    """Get historical model performance metrics from saved metadata."""
    entries = []

    for category in CATEGORIES:
        # XGBoost metrics
        xgb_meta = model_registry.get_model_metadata(category)
        if xgb_meta and "metrics" in xgb_meta:
            m = xgb_meta["metrics"]
            entries.append(PerformanceEntry(
                category=category,
                model_type="xgboost",
                auc=m.get("auc"),
                precision=m.get("precision"),
                recall=m.get("recall"),
                f1=m.get("f1"),
                trained_at=model_registry.get_training_date(),
            ))

        # LSTM metrics
        lstm_meta = model_registry.get_lstm_metadata(category)
        if lstm_meta and "metrics" in lstm_meta:
            m = lstm_meta["metrics"]
            entries.append(PerformanceEntry(
                category=category,
                model_type="lstm",
                auc=m.get("auc"),
                precision=m.get("precision"),
                recall=m.get("recall"),
                f1=m.get("f1"),
                trained_at=model_registry.get_training_date(),
            ))

    status = model_registry.get_status()
    return PerformanceResponse(
        entries=entries,
        training_summary=status.get("training_summary"),
    )


@router.get("/performance/history")
async def get_performance_history():
    """Get performance metrics from all saved training runs."""
    model_dir = Path(settings.model_dir)
    history = []

    # Read training summary
    summary_path = model_dir / "training_summary.json"
    if summary_path.exists():
        with open(summary_path) as f:
            summary = json.load(f)
        history.append(summary)

    # Read historical summaries if they exist
    history_dir = model_dir / "history"
    if history_dir.exists():
        for p in sorted(history_dir.glob("training_summary_*.json")):
            with open(p) as f:
                history.append(json.load(f))

    return {"history": history, "total_runs": len(history)}
