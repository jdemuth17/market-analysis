"""
Ensemble layer that combines XGBoost and LSTM predictions.
"""
import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.linear_model import LogisticRegression

from app.config import settings

logger = logging.getLogger(__name__)


class EnsembleScorer:
    """Calibrates and combines XGBoost + LSTM predictions."""

    def __init__(self):
        self.weights: dict[str, dict[str, float]] = {}

    def calibrate(
        self,
        category: str,
        xgboost_preds: np.ndarray,
        lstm_preds: np.ndarray,
        y_true: np.ndarray,
    ) -> dict[str, float]:
        """
        Learn optimal weights for combining XGBoost and LSTM predictions.
        Uses logistic regression on stacked predictions.
        """
        X_stack = np.column_stack([xgboost_preds, lstm_preds])
        lr = LogisticRegression(fit_intercept=False, max_iter=1000)
        lr.fit(X_stack, y_true)

        # Normalize to sum to 1
        raw_weights = lr.coef_[0]
        total = raw_weights.sum()
        alpha = float(raw_weights[0] / total) if total > 0 else 0.5
        beta = float(raw_weights[1] / total) if total > 0 else 0.5

        self.weights[category] = {"xgboost": alpha, "lstm": beta}
        logger.info(f"Ensemble {category}: alpha={alpha:.3f} beta={beta:.3f}")
        return self.weights[category]

    def predict(
        self,
        category: str,
        xgboost_scores: np.ndarray,
        lstm_scores: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Combine predictions into final ensemble score (0-100).
        Falls back to XGBoost-only if LSTM not available.
        """
        if lstm_scores is None or category not in self.weights:
            # XGBoost only
            return xgboost_scores * 100

        w = self.weights[category]
        combined = (w["xgboost"] * xgboost_scores) + (w["lstm"] * lstm_scores)
        return np.clip(combined * 100, 0, 100)

    def save(self, path: Path):
        with open(path, "w") as f:
            json.dump(self.weights, f, indent=2)
        logger.info(f"Saved ensemble weights: {path}")

    def load(self, path: Path):
        with open(path) as f:
            self.weights = json.load(f)
        logger.info(f"Loaded ensemble weights: {path}")
