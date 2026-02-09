import logging
from datetime import date
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connection import get_session
from app.db.queries import get_stocks_by_tickers
from app.features.feature_builder import FeatureBuilder, ALL_FEATURES
from app.models.model_registry import model_registry, CATEGORIES

logger = logging.getLogger(__name__)
router = APIRouter()


class PredictRequest(BaseModel):
    tickers: list[str]
    categories: list[str] = CATEGORIES
    as_of_date: Optional[date] = None
    include_shap: bool = True


class FeatureImpact(BaseModel):
    feature: str
    impact: float
    value: float


class StockPrediction(BaseModel):
    ticker: str
    category: str
    xgboost_score: float
    lstm_score: Optional[float] = None
    ensemble_score: float
    predicted_return_pct: Optional[float] = None
    confidence: float
    top_features: list[FeatureImpact] = []


class PredictResponse(BaseModel):
    predictions: list[StockPrediction]
    total_tickers: int
    categories_scored: list[str]
    model_version: Optional[str] = None


@router.post("/predict", response_model=PredictResponse)
async def predict(
    request: PredictRequest,
    session: AsyncSession = Depends(get_session),
):
    """Score stocks using the XGBoost + LSTM ensemble."""
    if not model_registry.has_models():
        raise HTTPException(
            status_code=503,
            detail="No trained models available. Run backfill and training first.",
        )

    # Validate categories
    valid_categories = [c for c in request.categories if c in CATEGORIES]
    if not valid_categories:
        raise HTTPException(status_code=400, detail=f"Invalid categories. Must be one of: {CATEGORIES}")

    # Validate tickers list
    if not request.tickers:
        raise HTTPException(status_code=400, detail="At least one ticker is required")
    if len(request.tickers) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 tickers per request")

    # Look up stocks
    stocks = await get_stocks_by_tickers(session, request.tickers)
    if not stocks:
        raise HTTPException(status_code=404, detail="No matching stocks found")

    stock_map = {s.Ticker: s for s in stocks}
    as_of = request.as_of_date or date.today()

    # Load normalizer if available
    normalizer = model_registry.get_normalizer()

    # Build features
    builder = FeatureBuilder(session)
    predictions = []

    for ticker, stock in stock_map.items():
        feature_vector = await builder.build_snapshot(stock.Id, as_of)
        if feature_vector is None:
            logger.warning(f"Insufficient data for {ticker}, skipping")
            continue

        # Ensure feature columns match expected order
        missing_cols = [c for c in ALL_FEATURES if c not in feature_vector.columns]
        for col in missing_cols:
            feature_vector[col] = 0.0
        feature_vector = feature_vector[ALL_FEATURES]

        # Normalize features (match training distribution)
        if normalizer is not None:
            feature_normalized = normalizer.transform(feature_vector)
        else:
            feature_normalized = feature_vector

        for category in valid_categories:
            if category not in model_registry.xgboost_models:
                continue

            # XGBoost prediction
            xgb_model = model_registry.xgboost_models[category]
            xgb_prob = float(xgb_model.predict_proba(feature_normalized)[:, 1][0])

            # SHAP explanations (on normalized features, mapped to original names)
            top_features = []
            if request.include_shap:
                from app.models.xgboost_model import XGBoostScorer
                scorer = XGBoostScorer(category)
                scorer.model = xgb_model
                shap_results = scorer.get_shap_explanations(feature_normalized, top_n=5)
                if shap_results and shap_results[0]:
                    top_features = [
                        FeatureImpact(**f) for f in shap_results[0]
                    ]

            # LSTM prediction (if available)
            lstm_score = None
            if category in model_registry.lstm_models:
                sequence = await builder.build_sequence(stock.Id, as_of)
                if sequence is not None:
                    import torch
                    model = model_registry.lstm_models[category]
                    with torch.no_grad():
                        tensor = torch.FloatTensor(sequence.values).unsqueeze(0)
                        prob, return_pct = model(tensor)
                        lstm_score = float(prob[0][0])

            # Ensemble
            if lstm_score is not None and category in model_registry.ensemble_weights:
                w = model_registry.ensemble_weights[category]
                ensemble = (w["xgboost"] * xgb_prob + w["lstm"] * lstm_score) * 100
            else:
                ensemble = xgb_prob * 100

            predictions.append(StockPrediction(
                ticker=ticker,
                category=category,
                xgboost_score=round(xgb_prob * 100, 1),
                lstm_score=round(lstm_score * 100, 1) if lstm_score is not None else None,
                ensemble_score=round(ensemble, 1),
                confidence=round(xgb_prob, 3),
                top_features=top_features,
            ))

    return PredictResponse(
        predictions=predictions,
        total_tickers=len(stock_map),
        categories_scored=valid_categories,
        model_version=model_registry.get_training_date(),
    )
