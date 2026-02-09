"""
Phase 5 backfill: Generate ground truth labels from forward price returns.
"""
import logging

logger = logging.getLogger(__name__)


async def run_label_generation():
    """
    For each stock-day with features, compute forward returns and binary labels.

    Labels:
    - DayTrade: 1-day return > 2%
    - SwingTrade: 5-day return > 5%
    - ShortTermHold: 10-day return > 8%
    - LongTermHold: 30-day return > 15%
    """
    logger.info("Label generation starting")
    # TODO: Implement in Phase 2
    # 1. For each ticker with price history
    # 2. For each trading day (excluding last 30 days)
    # 3. Compute forward returns: (close[t+n] - close[t]) / close[t]
    # 4. Generate binary labels per threshold
    # 5. Store in a training_labels table or export to parquet
    raise NotImplementedError("Label generation will be implemented in Phase 2")
