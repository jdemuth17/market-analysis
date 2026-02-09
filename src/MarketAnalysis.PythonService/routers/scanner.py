"""Market scanner endpoints for top movers and broad screening."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
import yfinance as yf
import logging
import asyncio

from utils.ticker_lists import get_tickers_for_index
from utils.rate_limiter import yahoo_rate_limiter

router = APIRouter()
logger = logging.getLogger(__name__)


class TickerMover(BaseModel):
    ticker: str
    name: Optional[str] = None
    current_price: Optional[float] = None
    previous_close: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None
    volume: Optional[int] = None
    avg_volume: Optional[int] = None
    volume_ratio: Optional[float] = None
    market_cap: Optional[float] = None
    sector: Optional[str] = None
    error: Optional[str] = None


class TopMoversResponse(BaseModel):
    top_gainers: list[TickerMover]
    top_losers: list[TickerMover]
    most_active: list[TickerMover]
    total_scanned: int
    errors: int


class ScanRequest(BaseModel):
    index: str = Field(default="sp500", description="Index to scan: sp500, nasdaq100")
    top_n: int = Field(default=25, ge=5, le=100, description="Number of results per category")


def _fetch_movers_data(tickers: list[str]) -> list[TickerMover]:
    """Fetch current price data for a list of tickers."""
    results: list[TickerMover] = []
    chunk_size = 50

    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i : i + chunk_size]
        yahoo_rate_limiter.wait()

        try:
            logger.info(f"Scanning {len(chunk)} tickers for movers (chunk {i // chunk_size + 1})")
            # Use yfinance Tickers to get info in bulk
            for ticker_str in chunk:
                try:
                    yahoo_rate_limiter.wait()
                    t = yf.Ticker(ticker_str)
                    info = t.info or {}

                    current = info.get("currentPrice") or info.get("regularMarketPrice")
                    prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")

                    change = None
                    change_pct = None
                    if current and prev_close and prev_close != 0:
                        change = current - prev_close
                        change_pct = (change / prev_close) * 100

                    vol = info.get("volume") or info.get("regularMarketVolume")
                    avg_vol = info.get("averageVolume") or info.get("averageDailyVolume10Day")
                    vol_ratio = None
                    if vol and avg_vol and avg_vol > 0:
                        vol_ratio = vol / avg_vol

                    results.append(TickerMover(
                        ticker=ticker_str,
                        name=info.get("shortName") or info.get("longName"),
                        current_price=current,
                        previous_close=prev_close,
                        change=round(change, 4) if change is not None else None,
                        change_percent=round(change_pct, 4) if change_pct is not None else None,
                        volume=vol,
                        avg_volume=avg_vol,
                        volume_ratio=round(vol_ratio, 2) if vol_ratio is not None else None,
                        market_cap=info.get("marketCap"),
                        sector=info.get("sector"),
                    ))
                except Exception as e:
                    logger.warning(f"Error fetching {ticker_str}: {e}")
                    results.append(TickerMover(ticker=ticker_str, error=str(e)))
        except Exception as e:
            logger.error(f"Chunk error: {e}")
            for t in chunk:
                results.append(TickerMover(ticker=t, error=str(e)))

    return results


@router.post("/top-movers", response_model=TopMoversResponse)
async def get_top_movers(request: ScanRequest):
    """Scan an index for top gainers, losers, and most active stocks."""
    try:
        tickers = get_tickers_for_index(request.index)
        logger.info(f"Scanning {len(tickers)} tickers from {request.index} for top movers")

        movers = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _fetch_movers_data(tickers)
        )

        valid = [m for m in movers if m.error is None and m.change_percent is not None]
        errors = len([m for m in movers if m.error is not None])

        top_n = request.top_n

        top_gainers = sorted(valid, key=lambda m: m.change_percent or 0, reverse=True)[:top_n]
        top_losers = sorted(valid, key=lambda m: m.change_percent or 0)[:top_n]
        most_active = sorted(valid, key=lambda m: m.volume_ratio or 0, reverse=True)[:top_n]

        return TopMoversResponse(
            top_gainers=top_gainers,
            top_losers=top_losers,
            most_active=most_active,
            total_scanned=len(tickers),
            errors=errors,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Top movers error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
