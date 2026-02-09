"""
Phase 2 backfill: Run chart pattern detection on historical price data.
Calls the existing Python service /api/technicals/patterns endpoint.
"""
import asyncio
import logging
from datetime import date, timedelta

import aiohttp
import pandas as pd
from sqlalchemy import select, func

from app.config import settings
from app.db.connection import async_session
from app.db.models import Stock, PriceHistory
from app.db.writes import insert_technical_signal
from app.db.queries import get_active_stocks, get_price_history_df

logger = logging.getLogger(__name__)

ALL_PATTERNS = [
    "double_top", "double_bottom",
    "head_and_shoulders", "inverse_head_and_shoulders",
    "bull_flag", "bear_flag",
    "ascending_triangle", "descending_triangle", "symmetrical_triangle",
    "rising_wedge", "falling_wedge",
    "pennant", "cup_and_handle",
]

# Map Python service direction strings to EF Core enum values
DIRECTION_MAP = {
    "bullish": "Bullish",
    "bearish": "Bearish",
    "neutral": "Neutral",
}

# Map Python service pattern strings to EF Core enum values
PATTERN_MAP = {
    "double_top": "DoubleTop",
    "double_bottom": "DoubleBottom",
    "head_and_shoulders": "HeadAndShoulders",
    "inverse_head_and_shoulders": "InverseHeadAndShoulders",
    "bull_flag": "BullFlag",
    "bear_flag": "BearFlag",
    "ascending_triangle": "AscendingTriangle",
    "descending_triangle": "DescendingTriangle",
    "symmetrical_triangle": "SymmetricalTriangle",
    "rising_wedge": "RisingWedge",
    "falling_wedge": "FallingWedge",
    "pennant": "Pennant",
    "cup_and_handle": "CupAndHandle",
}


async def _call_pattern_detection(
    http: aiohttp.ClientSession,
    ticker: str,
    bars: list[dict],
    lookback_days: int = 120,
) -> list[dict]:
    """Call existing Python service for pattern detection."""
    url = f"{settings.python_service_url}/api/technicals/patterns"
    payload = {
        "ticker": ticker,
        "bars": bars,
        "patterns": ALL_PATTERNS,
        "lookback_days": lookback_days,
    }

    try:
        async with http.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("detected_patterns", [])
            else:
                text = await resp.text()
                logger.warning(f"Pattern detection failed for {ticker}: {resp.status} {text[:200]}")
                return []
    except Exception as e:
        logger.warning(f"Pattern detection request failed for {ticker}: {e}")
        return []


def _df_to_bars(df: pd.DataFrame) -> list[dict]:
    """Convert a price DataFrame to the bar format expected by the Python service."""
    bars = []
    for _, row in df.iterrows():
        bars.append({
            "date": str(row["date"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "adj_close": float(row.get("adj_close", row["close"])),
            "volume": int(row["volume"]),
        })
    return bars


async def run_technical_backfill(start_date: str):
    """
    Run chart pattern detection on historical price data for all active stocks.
    Uses sliding windows to detect patterns at different points in history.
    """
    logger.info(f"Technical backfill starting from {start_date}")

    # Check Python service is available
    async with aiohttp.ClientSession() as http:
        try:
            async with http.get(f"{settings.python_service_url}/api/health") as resp:
                if resp.status != 200:
                    raise RuntimeError("Python service not healthy")
        except Exception as e:
            raise RuntimeError(f"Python service unavailable at {settings.python_service_url}: {e}")

    async with async_session() as session:
        stocks = await get_active_stocks(session)

    logger.info(f"Processing {len(stocks)} stocks for technical analysis")
    total_signals = 0
    total_failed = 0
    start = date.fromisoformat(start_date)

    async with aiohttp.ClientSession() as http:
        for idx, stock in enumerate(stocks):
            try:
                # Get full price history
                async with async_session() as session:
                    prices = await get_price_history_df(
                        session, stock.Id,
                        start_date=start,
                        limit=1000,
                    )

                if len(prices) < 120:
                    logger.debug(f"{stock.Ticker}: insufficient price history ({len(prices)} days)")
                    continue

                # Slide a window across the history, detecting patterns at intervals
                # Process every 30 trading days to balance coverage vs API calls
                window_size = settings.backfill_technical_lookback
                step_size = 30
                dates = prices["date"].tolist()

                signals_for_stock = 0

                for window_end_idx in range(window_size, len(dates), step_size):
                    window = prices.iloc[window_end_idx - window_size:window_end_idx]
                    bars = _df_to_bars(window)

                    detected = await _call_pattern_detection(
                        http, stock.Ticker, bars, lookback_days=window_size
                    )

                    if detected:
                        async with async_session() as session:
                            for pattern in detected:
                                pattern_type = PATTERN_MAP.get(
                                    pattern.get("pattern_type", ""), pattern.get("pattern_type", "")
                                )
                                direction = DIRECTION_MAP.get(
                                    pattern.get("direction", "neutral"), "Neutral"
                                )

                                detected_date = dates[window_end_idx - 1]
                                if isinstance(detected_date, str):
                                    detected_date = date.fromisoformat(detected_date)

                                start_date_val = None
                                if pattern.get("start_date"):
                                    try:
                                        start_date_val = date.fromisoformat(str(pattern["start_date"]))
                                    except ValueError:
                                        pass

                                end_date_val = None
                                if pattern.get("end_date"):
                                    try:
                                        end_date_val = date.fromisoformat(str(pattern["end_date"]))
                                    except ValueError:
                                        pass

                                signal = await insert_technical_signal(
                                    session,
                                    stock_id=stock.Id,
                                    detected_date=detected_date,
                                    pattern_type=pattern_type,
                                    direction=direction,
                                    confidence=float(pattern.get("confidence", 50)),
                                    start_date=start_date_val,
                                    end_date=end_date_val,
                                    status=pattern.get("status", "confirmed"),
                                    key_price_levels=pattern.get("key_levels"),
                                    metadata=pattern.get("metadata"),
                                )
                                if signal:
                                    signals_for_stock += 1

                            await session.commit()

                    # Rate limit to avoid overwhelming the Python service
                    await asyncio.sleep(0.1)

                total_signals += signals_for_stock
                if (idx + 1) % 50 == 0:
                    logger.info(
                        f"Progress: {idx + 1}/{len(stocks)} stocks, "
                        f"{total_signals} total signals detected"
                    )

            except Exception as e:
                logger.error(f"Technical backfill failed for {stock.Ticker}: {e}")
                total_failed += 1

    logger.info(
        f"Technical backfill complete: {total_signals} signals stored, "
        f"{total_failed} stocks failed"
    )
