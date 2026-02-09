"""
Phase 2 backfill: Run technical analysis on historical price windows.
"""
import logging

logger = logging.getLogger(__name__)


async def run_technical_backfill(start_date: str):
    """
    Run chart pattern detection on historical price data.
    Calls existing Python service /api/technicals/full-analysis for each ticker+day.
    """
    logger.info(f"Technical backfill starting from {start_date}")
    # TODO: Implement in Phase 2
    # 1. For each ticker with price history
    # 2. For each trading day in range
    # 3. Take trailing 120-day OHLCV window
    # 4. Call existing Python service /api/technicals/full-analysis
    # 5. Store TechnicalSignal records
    raise NotImplementedError("Technical backfill will be implemented in Phase 2")
