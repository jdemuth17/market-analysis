"""
Phase 3 backfill: Fetch quarterly fundamental snapshots from yfinance.
"""
import logging

logger = logging.getLogger(__name__)


async def run_fundamental_backfill(start_date: str):
    """
    Fetch quarterly fundamental data and compute scores.
    Uses yfinance directly for historical financials.
    """
    logger.info(f"Fundamental backfill starting from {start_date}")
    # TODO: Implement in Phase 2
    # 1. For each ticker in universe
    # 2. Fetch quarterly financials from yfinance (income_stmt, balance_sheet, cashflow)
    # 3. Compute Value, Quality, Growth, Safety scores per quarter
    # 4. Store FundamentalSnapshot records
    raise NotImplementedError("Fundamental backfill will be implemented in Phase 2")
