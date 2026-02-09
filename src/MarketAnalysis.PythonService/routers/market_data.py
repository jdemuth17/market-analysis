"""Market data API endpoints."""

from fastapi import APIRouter, HTTPException
import logging

from models.market_data import (
    FetchPricesRequest, FetchPricesResponse,
    FetchFundamentalsRequest, FetchFundamentalsResponse,
)
from services.yahoo_fetcher import YahooFetcher
from utils.ticker_lists import get_tickers_for_index

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/fetch-prices", response_model=FetchPricesResponse)
async def fetch_prices(request: FetchPricesRequest):
    """Fetch OHLCV price data for multiple tickers."""
    try:
        import asyncio
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: YahooFetcher.fetch_prices(request.tickers, request.period, request.interval),
        )
        return result
    except Exception as e:
        logger.error(f"Price fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fetch-fundamentals", response_model=FetchFundamentalsResponse)
async def fetch_fundamentals(request: FetchFundamentalsRequest):
    """Fetch fundamental data for multiple tickers."""
    try:
        import asyncio
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: YahooFetcher.fetch_fundamentals(request.tickers),
        )
        return result
    except Exception as e:
        logger.error(f"Fundamentals fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ticker-lists/{index_name}")
async def get_ticker_list(index_name: str):
    """Get ticker list for a named index (sp500, nasdaq100)."""
    try:
        tickers = get_tickers_for_index(index_name)
        return {"index": index_name, "tickers": tickers, "count": len(tickers)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Ticker list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
