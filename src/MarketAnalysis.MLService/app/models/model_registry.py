"""
Central registry that loads/stores trained model artifacts.
"""
import json
import logging
from pathlib import Path
from typing import Optional

import xgboost as xgb

from app.config import settings

logger = logging.getLogger(__name__)

CATEGORIES = ["DayTrade", "SwingTrade", "ShortTermHold", "LongTermHold"]


class ModelRegistry:
    def __init__(self):
        self.xgboost_models: dict[str, xgb.XGBClassifier] = {}
        self.lstm_models: dict[str, object] = {}  # PyTorch models loaded lazily
        self.ensemble_weights: dict[str, dict[str, float]] = {}
        self.model_dir = Path(settings.model_dir)
        self._normalizer = None
        self._training_summary: Optional[dict] = None
        self._model_metadata: dict[str, dict] = {}
        self._lstm_metadata: dict[str, dict] = {}

    async def load_all(self):
        """Load all available trained models from disk."""
        logger.info(f"Loading models from {self.model_dir}")
        loaded = 0

        for category in CATEGORIES:
            # XGBoost
            xgb_path = self.model_dir / f"xgboost_{category.lower()}.json"
            if xgb_path.exists():
                model = xgb.XGBClassifier()
                model.load_model(str(xgb_path))
                self.xgboost_models[category] = model
                logger.info(f"Loaded XGBoost model: {category}")
                loaded += 1

            # XGBoost metadata
            meta_path = self.model_dir / f"xgboost_{category.lower()}_metadata.json"
            if meta_path.exists():
                with open(meta_path) as f:
                    self._model_metadata[category] = json.load(f)

            # LSTM
            lstm_path = self.model_dir / f"lstm_{category.lower()}.pt"
            if lstm_path.exists():
                self._load_lstm(category, lstm_path)
                loaded += 1

            # LSTM metadata
            lstm_meta_path = self.model_dir / f"lstm_{category.lower()}_metadata.json"
            if lstm_meta_path.exists():
                with open(lstm_meta_path) as f:
                    self._lstm_metadata[category] = json.load(f)

        # Ensemble weights
        weights_path = self.model_dir / "ensemble_weights.json"
        if weights_path.exists():
            with open(weights_path) as f:
                self.ensemble_weights = json.load(f)
            logger.info("Loaded ensemble weights")
            loaded += 1

        # Normalizer
        normalizer_path = self.model_dir / "normalizer.json"
        if normalizer_path.exists():
            from app.features.normalizer import FeatureNormalizer
            self._normalizer = FeatureNormalizer()
            self._normalizer.load(normalizer_path)
            loaded += 1

        # Training summary
        summary_path = self.model_dir / "training_summary.json"
        if summary_path.exists():
            with open(summary_path) as f:
                self._training_summary = json.load(f)

        if loaded == 0:
            logger.warning("No trained models found. Run backfill + training first.")
        else:
            logger.info(f"Loaded {loaded} model artifacts")

    def _load_lstm(self, category: str, path: Path):
        """Load a PyTorch LSTM model."""
        try:
            import torch
            from app.models.lstm_model import StockLSTM

            # Detect actual input_size from saved state dict
            state_dict = torch.load(str(path), map_location="cpu", weights_only=True)
            # lstm1.weight_ih_l0 shape is (4*hidden_size, input_size)
            actual_input_size = state_dict["lstm1.weight_ih_l0"].shape[1]

            model = StockLSTM(
                input_size=actual_input_size,
                hidden_size_1=settings.lstm_hidden_size_1,
                hidden_size_2=settings.lstm_hidden_size_2,
                dropout=settings.lstm_dropout,
            )
            model.load_state_dict(state_dict)
            model.eval()
            self.lstm_models[category] = model
            logger.info(f"Loaded LSTM model: {category}")
        except Exception as e:
            logger.error(f"Failed to load LSTM model {category}: {e}")

    def has_models(self) -> bool:
        return len(self.xgboost_models) > 0

    def get_normalizer(self):
        """Return the fitted normalizer, or None if not available."""
        return self._normalizer

    def get_training_date(self) -> Optional[str]:
        """Return the date of the most recent training run."""
        if self._training_summary:
            return self._training_summary.get("trained_at")
        return None

    def get_model_metadata(self, category: str) -> Optional[dict]:
        """Return XGBoost training metadata for a specific category."""
        return self._model_metadata.get(category)

    def get_lstm_metadata(self, category: str) -> Optional[dict]:
        """Return LSTM training metadata for a specific category."""
        return self._lstm_metadata.get(category)

    def get_status(self) -> dict:
        return {
            "xgboost_models": list(self.xgboost_models.keys()),
            "lstm_models": list(self.lstm_models.keys()),
            "has_ensemble_weights": len(self.ensemble_weights) > 0,
            "has_normalizer": self._normalizer is not None,
            "trained_at": self.get_training_date(),
            "training_summary": self._training_summary,
        }


model_registry = ModelRegistry()
