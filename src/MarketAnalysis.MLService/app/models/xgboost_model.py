"""
XGBoost model wrapper for cross-sectional stock scoring.
"""
import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, precision_score, recall_score

from app.config import settings

logger = logging.getLogger(__name__)


class XGBoostScorer:
    """Trains and predicts with XGBoost for a single report category."""

    def __init__(self, category: str):
        self.category = category
        self.model: Optional[xgb.XGBClassifier] = None

    def train(
        self,
        X: pd.DataFrame,
        y_class: pd.Series,
        y_reg: Optional[pd.Series] = None,
    ) -> dict:
        """
        Train the XGBoost classifier.

        Returns metrics dict with AUC, precision, recall.
        """
        X_train, X_val, y_train, y_val = train_test_split(
            X, y_class, test_size=0.2, shuffle=False,  # time-ordered, no shuffle
        )

        self.model = xgb.XGBClassifier(
            n_estimators=settings.xgboost_n_estimators,
            max_depth=settings.xgboost_max_depth,
            learning_rate=settings.xgboost_learning_rate,
            objective="binary:logistic",
            eval_metric="auc",
            tree_method="hist",
            random_state=42,
        )

        self.model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )

        # Evaluate
        y_pred_proba = self.model.predict_proba(X_val)[:, 1]
        y_pred = (y_pred_proba >= 0.5).astype(int)

        metrics = {
            "category": self.category,
            "auc": float(roc_auc_score(y_val, y_pred_proba)),
            "precision": float(precision_score(y_val, y_pred, zero_division=0)),
            "recall": float(recall_score(y_val, y_pred, zero_division=0)),
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "positive_rate_train": float(y_train.mean()),
            "positive_rate_val": float(y_val.mean()),
        }

        logger.info(
            f"XGBoost {self.category}: AUC={metrics['auc']:.3f} "
            f"P={metrics['precision']:.3f} R={metrics['recall']:.3f}"
        )
        return metrics

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return probability scores (0-1) for each row."""
        if self.model is None:
            raise RuntimeError(f"XGBoost model for {self.category} not trained/loaded")
        return self.model.predict_proba(X)[:, 1]

    def get_shap_explanations(self, X: pd.DataFrame, top_n: int = 5) -> list[list[dict]]:
        """
        Get SHAP feature importance for each prediction.
        Returns list of lists (one per row) of top_n feature impacts.
        """
        try:
            import shap
            explainer = shap.TreeExplainer(self.model)
            shap_values = explainer.shap_values(X)

            explanations = []
            feature_names = list(X.columns)

            for i in range(len(X)):
                row_shap = shap_values[i]
                # Sort by absolute impact
                indices = np.argsort(np.abs(row_shap))[::-1][:top_n]
                top_features = [
                    {
                        "feature": feature_names[idx],
                        "impact": float(row_shap[idx]),
                        "value": float(X.iloc[i, idx]),
                    }
                    for idx in indices
                ]
                explanations.append(top_features)

            return explanations
        except Exception as e:
            logger.warning(f"SHAP explanation failed: {e}")
            return [[] for _ in range(len(X))]

    def save(self, path: Path):
        if self.model is None:
            raise RuntimeError("No model to save")
        self.model.save_model(str(path))
        logger.info(f"Saved XGBoost model: {path}")

    def load(self, path: Path):
        self.model = xgb.XGBClassifier()
        self.model.load_model(str(path))
        logger.info(f"Loaded XGBoost model: {path}")
