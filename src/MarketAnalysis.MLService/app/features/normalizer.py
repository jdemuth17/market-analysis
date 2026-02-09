"""
Feature normalization utilities for training and inference.
"""
import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class FeatureNormalizer:
    """Z-score normalization with saved statistics for consistent inference."""

    def __init__(self):
        self.mean: Optional[pd.Series] = None
        self.std: Optional[pd.Series] = None

    def fit(self, X: pd.DataFrame) -> "FeatureNormalizer":
        """Compute mean and std from training data."""
        self.mean = X.mean()
        self.std = X.std().replace(0, 1)  # avoid division by zero
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Apply normalization using stored statistics."""
        if self.mean is None or self.std is None:
            raise RuntimeError("Normalizer not fitted. Call fit() first.")
        return (X - self.mean) / self.std

    def fit_transform(self, X: pd.DataFrame) -> pd.DataFrame:
        return self.fit(X).transform(X)

    def save(self, path: Path):
        stats = {
            "mean": self.mean.to_dict(),
            "std": self.std.to_dict(),
        }
        with open(path, "w") as f:
            json.dump(stats, f, indent=2)
        logger.info(f"Saved normalizer: {path}")

    def load(self, path: Path):
        with open(path) as f:
            stats = json.load(f)
        self.mean = pd.Series(stats["mean"])
        self.std = pd.Series(stats["std"])
        logger.info(f"Loaded normalizer: {path}")
