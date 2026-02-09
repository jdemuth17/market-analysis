"""
XGBoost model wrapper for cross-sectional stock scoring.

Supports:
- Walk-forward (time-series) cross-validation
- Class imbalance handling via scale_pos_weight
- SHAP explanations
- Feature importance extraction
"""
import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    roc_auc_score, precision_score, recall_score, f1_score,
    brier_score_loss, log_loss,
)
from sklearn.model_selection import TimeSeriesSplit

from app.config import settings

logger = logging.getLogger(__name__)


class XGBoostScorer:
    """Trains and predicts with XGBoost for a single report category."""

    def __init__(self, category: str):
        self.category = category
        self.model: Optional[xgb.XGBClassifier] = None
        self.feature_names: list[str] = []
        self.training_metrics: dict = {}

    def train(
        self,
        X: pd.DataFrame,
        y_class: pd.Series,
        y_reg: Optional[pd.Series] = None,
    ) -> dict:
        """
        Train the XGBoost classifier with walk-forward validation.

        Uses TimeSeriesSplit (5 folds) for cross-validation, then trains
        a final model on 80% of data and evaluates on the last 20%.

        Returns metrics dict with AUC, precision, recall, F1, and CV scores.
        """
        self.feature_names = list(X.columns)

        # Handle class imbalance
        n_pos = int(y_class.sum())
        n_neg = len(y_class) - n_pos
        scale_pos = n_neg / max(n_pos, 1)

        # Walk-forward cross-validation
        tscv = TimeSeriesSplit(n_splits=5)
        cv_aucs = []

        for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
            X_fold_train = X.iloc[train_idx]
            y_fold_train = y_class.iloc[train_idx]
            X_fold_val = X.iloc[val_idx]
            y_fold_val = y_class.iloc[val_idx]

            fold_model = xgb.XGBClassifier(
                n_estimators=settings.xgboost_n_estimators,
                max_depth=settings.xgboost_max_depth,
                learning_rate=settings.xgboost_learning_rate,
                scale_pos_weight=scale_pos,
                objective="binary:logistic",
                eval_metric="auc",
                tree_method="hist",
                early_stopping_rounds=50,
                random_state=42,
            )
            fold_model.fit(
                X_fold_train, y_fold_train,
                eval_set=[(X_fold_val, y_fold_val)],
                verbose=False,
            )

            y_fold_proba = fold_model.predict_proba(X_fold_val)[:, 1]
            try:
                fold_auc = roc_auc_score(y_fold_val, y_fold_proba)
                cv_aucs.append(fold_auc)
            except ValueError:
                pass  # Skip folds with single class

        # Final model: train on 80%, evaluate on last 20%
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_val = y_class.iloc[:split_idx], y_class.iloc[split_idx:]

        self.model = xgb.XGBClassifier(
            n_estimators=settings.xgboost_n_estimators,
            max_depth=settings.xgboost_max_depth,
            learning_rate=settings.xgboost_learning_rate,
            scale_pos_weight=scale_pos,
            objective="binary:logistic",
            eval_metric="auc",
            tree_method="hist",
            early_stopping_rounds=50,
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
            "f1": float(f1_score(y_val, y_pred, zero_division=0)),
            "brier_score": float(brier_score_loss(y_val, y_pred_proba)),
            "log_loss": float(log_loss(y_val, y_pred_proba)),
            "cv_auc_mean": float(np.mean(cv_aucs)) if cv_aucs else 0.0,
            "cv_auc_std": float(np.std(cv_aucs)) if cv_aucs else 0.0,
            "cv_folds": len(cv_aucs),
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "positive_rate_train": float(y_train.mean()),
            "positive_rate_val": float(y_val.mean()),
            "scale_pos_weight": round(scale_pos, 2),
            "best_iteration": self.model.best_iteration if hasattr(self.model, 'best_iteration') else settings.xgboost_n_estimators,
        }

        self.training_metrics = metrics

        logger.info(
            f"XGBoost {self.category}: AUC={metrics['auc']:.3f} "
            f"P={metrics['precision']:.3f} R={metrics['recall']:.3f} "
            f"F1={metrics['f1']:.3f} CV_AUC={metrics['cv_auc_mean']:.3f}±{metrics['cv_auc_std']:.3f}"
        )
        return metrics

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return probability scores (0-1) for each row."""
        if self.model is None:
            raise RuntimeError(f"XGBoost model for {self.category} not trained/loaded")
        return self.model.predict_proba(X)[:, 1]

    def get_feature_importance(self, importance_type: str = "gain") -> list[dict]:
        """
        Get feature importance rankings.

        Args:
            importance_type: One of 'weight', 'gain', 'cover'

        Returns:
            Sorted list of {feature, importance} dicts.
        """
        if self.model is None:
            return []

        importance = self.model.get_booster().get_score(importance_type=importance_type)

        # Map xgboost feature names (f0, f1, ...) back to real names
        result = []
        for feat_key, imp_val in importance.items():
            if feat_key.startswith("f") and feat_key[1:].isdigit():
                idx = int(feat_key[1:])
                name = self.feature_names[idx] if idx < len(self.feature_names) else feat_key
            else:
                name = feat_key
            result.append({"feature": name, "importance": float(imp_val)})

        result.sort(key=lambda x: x["importance"], reverse=True)
        return result

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
        path.parent.mkdir(parents=True, exist_ok=True)
        self.model.save_model(str(path))
        logger.info(f"Saved XGBoost model: {path}")

    def load(self, path: Path):
        self.model = xgb.XGBClassifier()
        self.model.load_model(str(path))
        logger.info(f"Loaded XGBoost model: {path}")

    def save_metadata(self, path: Path):
        """Save training metadata (metrics, feature importance, config)."""
        metadata = {
            "category": self.category,
            "metrics": self.training_metrics,
            "feature_importance": self.get_feature_importance("gain"),
            "feature_names": self.feature_names,
            "config": {
                "n_estimators": settings.xgboost_n_estimators,
                "max_depth": settings.xgboost_max_depth,
                "learning_rate": settings.xgboost_learning_rate,
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
        logger.info(f"Saved XGBoost metadata: {path}")
