"""
Model information and feature importance endpoints.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.model_registry import model_registry, CATEGORIES

logger = logging.getLogger(__name__)
router = APIRouter()


class FeatureImportanceItem(BaseModel):
    feature: str
    importance: float


class ModelInfo(BaseModel):
    category: str
    model_type: str
    metrics: Optional[dict] = None
    feature_importance: list[FeatureImportanceItem] = []
    config: Optional[dict] = None


class ModelsResponse(BaseModel):
    models: list[ModelInfo]
    trained_at: Optional[str] = None
    training_summary: Optional[dict] = None


@router.get("/models", response_model=ModelsResponse)
async def list_models():
    """Get information about all loaded models, their metrics, and training info."""
    models = []

    for category in CATEGORIES:
        # XGBoost
        if category in model_registry.xgboost_models:
            metadata = model_registry.get_model_metadata(category)

            importance = []
            if metadata and "feature_importance" in metadata:
                importance = [
                    FeatureImportanceItem(**fi)
                    for fi in metadata["feature_importance"][:20]
                ]

            models.append(ModelInfo(
                category=category,
                model_type="xgboost",
                metrics=metadata.get("metrics") if metadata else None,
                feature_importance=importance,
                config=metadata.get("config") if metadata else None,
            ))

        # LSTM
        if category in model_registry.lstm_models:
            lstm_meta = model_registry.get_lstm_metadata(category)
            models.append(ModelInfo(
                category=category,
                model_type="lstm",
                metrics=lstm_meta.get("metrics") if lstm_meta else None,
                config=lstm_meta.get("config") if lstm_meta else None,
            ))

    status = model_registry.get_status()
    return ModelsResponse(
        models=models,
        trained_at=status.get("trained_at"),
        training_summary=status.get("training_summary"),
    )


@router.get("/models/{category}/importance")
async def get_feature_importance(category: str, top_n: int = 20):
    """Get feature importance rankings for a specific category's XGBoost model."""
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {CATEGORIES}")

    if category not in model_registry.xgboost_models:
        raise HTTPException(status_code=404, detail=f"No trained model found for {category}")

    metadata = model_registry.get_model_metadata(category)
    if not metadata or "feature_importance" not in metadata:
        # Compute live from model if metadata not saved
        from app.models.xgboost_model import XGBoostScorer
        scorer = XGBoostScorer(category)
        scorer.model = model_registry.xgboost_models[category]
        importance = scorer.get_feature_importance("gain")[:top_n]
    else:
        importance = metadata["feature_importance"][:top_n]

    return {
        "category": category,
        "importance_type": "gain",
        "features": importance,
    }
