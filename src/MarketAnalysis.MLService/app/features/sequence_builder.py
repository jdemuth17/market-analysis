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


def build_training_sequences(
    dataset: pd.DataFrame,
    feature_cols: list[str],
    label_col: str,
    return_col: Optional[str] = None,
    sequence_length: int = None,
) -> tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
    """
    Build LSTM training sequences from the full parquet dataset.

    Groups by ticker, builds per-stock sliding window sequences (ensuring
    no cross-stock contamination), then combines all sequences.

    Args:
        dataset: Full training DataFrame with ticker, date, features, and labels.
                 Must be sorted by [ticker, date].
        feature_cols: List of feature column names to include.
        label_col: Binary label column name (e.g. 'label_daytrade').
        return_col: Optional regression target column (e.g. 'return_1d').
        sequence_length: Sliding window size (default from config).

    Returns:
        X: (n_total_sequences, sequence_length, n_features) float32
        y_class: (n_total_sequences,) binary labels
        y_reg: (n_total_sequences,) return values or None
    """
    seq_len = sequence_length or settings.lstm_sequence_length

    all_X = []
    all_y_class = []
    all_y_reg = []

    tickers = dataset["ticker"].unique()
    skipped = 0

    for ticker in tickers:
        stock_data = dataset[dataset["ticker"] == ticker].sort_values("date").reset_index(drop=True)

        # Need enough rows for at least 1 sequence + valid label
        if len(stock_data) < seq_len + 1:
            skipped += 1
            continue

        features = stock_data[feature_cols].values.astype(np.float32)
        labels = stock_data[label_col].values
        returns = stock_data[return_col].values if return_col and return_col in stock_data.columns else None

        for i in range(seq_len, len(stock_data)):
            # Skip if label is NaN
            if np.isnan(labels[i]):
                continue

            seq = features[i - seq_len:i]

            # Z-score normalize within each sequence
            mean = seq.mean(axis=0)
            std = seq.std(axis=0)
            std[std == 0] = 1
            seq_normalized = (seq - mean) / std

            all_X.append(seq_normalized)
            all_y_class.append(labels[i])

            if returns is not None and not np.isnan(returns[i]):
                all_y_reg.append(returns[i])

    if not all_X:
        logger.warning(f"No sequences built for {label_col}")
        return np.array([]), np.array([]), None

    X = np.stack(all_X)
    y_class = np.array(all_y_class, dtype=np.float32)
    y_reg = np.array(all_y_reg, dtype=np.float32) if all_y_reg and len(all_y_reg) == len(all_X) else None

    logger.info(
        f"Built {len(X)} sequences for {label_col} from {len(tickers) - skipped} stocks "
        f"({skipped} skipped, seq_len={seq_len})"
    )
    return X, y_class, y_reg
