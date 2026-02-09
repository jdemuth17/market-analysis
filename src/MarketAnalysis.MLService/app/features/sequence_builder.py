"""
Sequence builder for LSTM training data.
Creates (sequence_length, num_features) tensors from feature snapshots.
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd

from app.config import settings

logger = logging.getLogger(__name__)


def build_sequences(
    feature_df: pd.DataFrame,
    labels_df: Optional[pd.DataFrame] = None,
    sequence_length: int = None,
) -> tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Convert a time-ordered feature DataFrame into sliding window sequences.

    Args:
        feature_df: DataFrame with shape (n_days, n_features), sorted by date ascending
        labels_df: Optional DataFrame with label columns aligned to feature_df
        sequence_length: Number of time steps per sequence (default from config)

    Returns:
        X: np.ndarray of shape (n_sequences, sequence_length, n_features)
        y_class: Optional np.ndarray of binary labels (n_sequences,)
        y_reg: Optional np.ndarray of return values (n_sequences,)
    """
    seq_len = sequence_length or settings.lstm_sequence_length
    n_rows = len(feature_df)

    if n_rows < seq_len + 1:
        logger.warning(f"Insufficient rows ({n_rows}) for sequences of length {seq_len}")
        return np.array([]), None, None

    features = feature_df.values.astype(np.float32)
    sequences = []
    y_class_list = []
    y_reg_list = []

    for i in range(seq_len, n_rows):
        seq = features[i - seq_len:i]

        # Z-score normalize within each sequence
        mean = seq.mean(axis=0)
        std = seq.std(axis=0)
        std[std == 0] = 1  # avoid division by zero
        seq_normalized = (seq - mean) / std

        sequences.append(seq_normalized)

        if labels_df is not None:
            y_class_list.append(labels_df.iloc[i].values[0])  # first label col
            if labels_df.shape[1] > 1:
                y_reg_list.append(labels_df.iloc[i].values[1])  # regression target

    X = np.stack(sequences)
    y_class = np.array(y_class_list) if y_class_list else None
    y_reg = np.array(y_reg_list) if y_reg_list else None

    logger.info(f"Built {len(sequences)} sequences of shape ({seq_len}, {features.shape[1]})")
    return X, y_class, y_reg
