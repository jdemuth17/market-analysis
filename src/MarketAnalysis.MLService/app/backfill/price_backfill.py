"""
Phase 1 backfill: Download 3 years of historical OHLCV data via yfinance.
"""
import asyncio
import logging
from datetime import date, datetime

import aiohttp
import yfinance as yf
import pandas as pd

from app.config import settings
from app.db.connection import async_session
from app.db.writes import get_or_create_stock, upsert_price_history_batch

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


async def _get_ticker_universe() -> list[str]:
    """Fetch S&P 500 + NASDAQ 100 tickers from existing Python service."""
    tickers = set()
    base_url = settings.python_service_url

    async with aiohttp.ClientSession() as http:
        for index in ["sp500", "nasdaq100"]:
            try:
                async with http.get(f"{base_url}/api/market-data/ticker-lists/{index}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tickers.update(data.get("tickers", []))
                        logger.info(f"Loaded {len(data.get('tickers', []))} tickers from {index}")
            except Exception as e:
                logger.warning(f"Failed to get {index} tickers from Python service: {e}")

    # Fallback: if Python service unavailable, use Wikipedia scrape
    if not tickers:
        logger.info("Python service unavailable, fetching tickers from Wikipedia")
        tickers = await _fallback_ticker_fetch()

    return sorted(tickers)


async def _fallback_ticker_fetch() -> set[str]:
    """Fallback: scrape S&P 500 and NASDAQ 100 tickers from Wikipedia."""
    tickers = set()
    try:
        # S&P 500
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        if tables:
            sp500 = tables[0]
            tickers.update(sp500["Symbol"].str.replace(".", "-").tolist())
            logger.info(f"Fetched {len(sp500)} S&P 500 tickers from Wikipedia")
    except Exception as e:
        logger.warning(f"Failed to fetch S&P 500 from Wikipedia: {e}")

    try:
        # NASDAQ 100
        tables = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100")
        if tables:
            for table in tables:
                if "Ticker" in table.columns:
                    tickers.update(table["Ticker"].tolist())
                    logger.info(f"Fetched NASDAQ 100 tickers from Wikipedia")
                    break
    except Exception as e:
        logger.warning(f"Failed to fetch NASDAQ 100 from Wikipedia: {e}")

    return tickers


def _download_prices(tickers: list[str], period: str = "3y") -> dict[str, pd.DataFrame]:
    """
    Download OHLCV data from yfinance. Runs in thread pool (blocking I/O).
    Returns dict of ticker -> DataFrame.
    """
    results = {}
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        batch_str = " ".join(batch)
        logger.info(f"Downloading prices for batch {i // BATCH_SIZE + 1}: {len(batch)} tickers")

        try:
            data = yf.download(
                batch_str,
                period=period,
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                threads=True,
            )

            if data.empty:
                logger.warning(f"No data returned for batch starting at {i}")
                continue

            # Handle single ticker vs multi-ticker response
            if len(batch) == 1:
                ticker = batch[0]
                df = data.copy()
                if not df.empty:
                    results[ticker] = df
            else:
                for ticker in batch:
                    try:
                        if ticker in data.columns.get_level_values(0):
                            df = data[ticker].dropna(subset=["Close"])
                            if not df.empty:
                                results[ticker] = df
                    except (KeyError, TypeError):
                        continue

        except Exception as e:
            logger.error(f"yfinance download failed for batch at {i}: {e}")

    return results


async def run_price_backfill(start_date: str):
    """
    Fetch 3 years of historical OHLCV data for S&P 500 + NASDAQ 100 tickers.
    Stores directly into PriceHistory table via SQLAlchemy.
    """
    logger.info(f"Price backfill starting from {start_date}")

    # Step 1: Get ticker universe
    tickers = await _get_ticker_universe()
    logger.info(f"Ticker universe: {len(tickers)} tickers")

    if not tickers:
        raise RuntimeError("No tickers found for backfill")

    # Step 2: Download prices (blocking I/O in thread pool)
    loop = asyncio.get_event_loop()
    price_data = await loop.run_in_executor(
        None, _download_prices, tickers, settings.backfill_price_period
    )
    logger.info(f"Downloaded price data for {len(price_data)} tickers")

    # Step 3: Store in database
    total_rows = 0
    failed = 0

    async with async_session() as session:
        for ticker, df in price_data.items():
            try:
                # Get or create stock record
                stock = await get_or_create_stock(session, ticker)

                # Convert DataFrame to row dicts
                rows = []
                for idx, row in df.iterrows():
                    row_date = idx.date() if hasattr(idx, "date") else idx
                    rows.append({
                        "date": row_date,
                        "open": float(row.get("Open", 0)),
                        "high": float(row.get("High", 0)),
                        "low": float(row.get("Low", 0)),
                        "close": float(row.get("Close", 0)),
                        "adj_close": float(row.get("Adj Close", row.get("Close", 0))),
                        "volume": int(row.get("Volume", 0)),
                    })

                if rows:
                    # Batch upsert in chunks of 500
                    for chunk_start in range(0, len(rows), 500):
                        chunk = rows[chunk_start:chunk_start + 500]
                        count = await upsert_price_history_batch(session, stock.Id, chunk)
                        total_rows += count

                    await session.commit()
                    logger.debug(f"{ticker}: {len(rows)} price rows stored")

            except Exception as e:
                logger.error(f"Failed to store prices for {ticker}: {e}")
                await session.rollback()
                failed += 1

    logger.info(
        f"Price backfill complete: {total_rows} rows stored, "
        f"{len(price_data)} tickers succeeded, {failed} failed"
    )
