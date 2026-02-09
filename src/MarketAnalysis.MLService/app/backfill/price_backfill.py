"""
Phase 1 backfill: Download 3 years of historical OHLCV data via yfinance.
"""
import logging

logger = logging.getLogger(__name__)


async def run_price_backfill(start_date: str):
    """
    Fetch historical price data for S&P 500 + NASDAQ 100 tickers.
    Calls the existing Python service /api/market-data/fetch-prices.
    """
    logger.info(f"Price backfill starting from {start_date}")
    # TODO: Implement in Phase 2
    # 1. Get ticker universe from existing Python service /api/market-data/ticker-lists/sp500 + nasdaq100
    # 2. Batch 50 tickers at a time
    # 3. Call existing Python service /api/market-data/fetch-prices with period="3y"
    # 4. Store via existing PriceHistory upsert logic
    raise NotImplementedError("Price backfill will be implemented in Phase 2")
