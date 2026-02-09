"""
Phase 3 backfill: Fetch quarterly fundamental snapshots from yfinance.
Computes Value, Quality, Growth, Safety scores matching existing Python service logic.
"""
import asyncio
import logging
import math
from datetime import date, datetime

import yfinance as yf

from app.config import settings
from app.db.connection import async_session
from app.db.writes import get_or_create_stock, insert_fundamental_snapshot
from app.db.queries import get_active_stocks

logger = logging.getLogger(__name__)


def _safe(val, default=None):
    """Safely extract a numeric value, returning default for NaN/None/Inf."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _compute_scores(info: dict) -> dict:
    """
    Compute Value, Quality, Growth, Safety scores (0-100) from yfinance info.
    Mirrors logic in existing Python service fundamental_analyzer.py.
    """
    # Value Score (0-100): P/E, Forward P/E, PEG, P/B, upside potential
    value_points = 0
    value_max = 0

    pe = _safe(info.get("trailingPE"))
    if pe is not None:
        value_max += 25
        if pe < 15:
            value_points += 25
        elif pe < 25:
            value_points += 25 * (1 - (pe - 15) / 10)

    fwd_pe = _safe(info.get("forwardPE"))
    if fwd_pe is not None:
        value_max += 20
        if fwd_pe < 15:
            value_points += 20
        elif fwd_pe < 25:
            value_points += 20 * (1 - (fwd_pe - 15) / 10)

    peg = _safe(info.get("pegRatio"))
    if peg is not None:
        value_max += 20
        if 0 < peg < 1:
            value_points += 20
        elif peg < 2:
            value_points += 20 * (1 - (peg - 1))

    pb = _safe(info.get("priceToBook"))
    if pb is not None:
        value_max += 15
        if pb < 1:
            value_points += 15
        elif pb < 3:
            value_points += 15 * (1 - (pb - 1) / 2)

    current = _safe(info.get("currentPrice"))
    target = _safe(info.get("targetMeanPrice"))
    if current and target and current > 0:
        value_max += 20
        upside = (target - current) / current
        if upside > 0.3:
            value_points += 20
        elif upside > 0:
            value_points += 20 * (upside / 0.3)

    value_score = (value_points / value_max * 100) if value_max > 0 else 50

    # Quality Score (0-100): Profit margin, ROE, FCF
    quality_points = 0
    quality_max = 0

    margin = _safe(info.get("profitMargins"))
    if margin is not None:
        quality_max += 35
        if margin > 0.2:
            quality_points += 35
        elif margin > 0:
            quality_points += 35 * (margin / 0.2)

    roe = _safe(info.get("returnOnEquity"))
    if roe is not None:
        quality_max += 35
        if roe > 0.2:
            quality_points += 35
        elif roe > 0:
            quality_points += 35 * (roe / 0.2)

    fcf = _safe(info.get("freeCashflow"))
    if fcf is not None:
        quality_max += 30
        if fcf > 0:
            quality_points += 30

    quality_score = (quality_points / quality_max * 100) if quality_max > 0 else 50

    # Growth Score (0-100): Revenue growth, earnings growth, EPS
    growth_points = 0
    growth_max = 0

    rev_growth = _safe(info.get("revenueGrowth"))
    if rev_growth is not None:
        growth_max += 40
        if rev_growth > 0.2:
            growth_points += 40
        elif rev_growth > 0:
            growth_points += 40 * (rev_growth / 0.2)

    earn_growth = _safe(info.get("earningsGrowth"))
    if earn_growth is not None:
        growth_max += 40
        if earn_growth > 0.2:
            growth_points += 40
        elif earn_growth > 0:
            growth_points += 40 * (earn_growth / 0.2)

    eps = _safe(info.get("trailingEps"))
    if eps is not None:
        growth_max += 20
        if eps > 0:
            growth_points += 20

    growth_score = (growth_points / growth_max * 100) if growth_max > 0 else 50

    # Safety Score (0-100): Debt/equity, FCF presence
    safety_points = 0
    safety_max = 0

    de = _safe(info.get("debtToEquity"))
    if de is not None:
        safety_max += 60
        if de < 50:
            safety_points += 60
        elif de < 150:
            safety_points += 60 * (1 - (de - 50) / 100)

    if fcf is not None:
        safety_max += 40
        if fcf > 0:
            safety_points += 40

    safety_score = (safety_points / safety_max * 100) if safety_max > 0 else 50

    # Composite: value 30%, quality 30%, growth 20%, safety 20%
    composite = (
        value_score * 0.30
        + quality_score * 0.30
        + growth_score * 0.20
        + safety_score * 0.20
    )

    return {
        "value_score": round(value_score, 1),
        "quality_score": round(quality_score, 1),
        "growth_score": round(growth_score, 1),
        "safety_score": round(safety_score, 1),
        "composite_score": round(composite, 1),
    }


def _fetch_fundamentals_for_tickers(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch fundamental data from yfinance for a list of tickers.
    Returns dict of ticker -> {metrics, scores, raw_info}.
    Runs in thread pool (blocking I/O).
    """
    results = {}

    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info or {}

            if not info or info.get("regularMarketPrice") is None:
                continue

            metrics = {
                "pe_ratio": _safe(info.get("trailingPE")),
                "forward_pe": _safe(info.get("forwardPE")),
                "peg_ratio": _safe(info.get("pegRatio")),
                "price_to_book": _safe(info.get("priceToBook")),
                "debt_to_equity": _safe(info.get("debtToEquity")),
                "profit_margin": _safe(info.get("profitMargins")),
                "operating_margin": _safe(info.get("operatingMargins")),
                "roe": _safe(info.get("returnOnEquity")),
                "free_cash_flow": _safe(info.get("freeCashflow")),
                "dividend_yield": _safe(info.get("dividendYield")),
                "revenue": _safe(info.get("totalRevenue")),
                "revenue_growth": _safe(info.get("revenueGrowth")),
                "earnings_growth": _safe(info.get("earningsGrowth")),
                "eps": _safe(info.get("trailingEps")),
                "market_cap": _safe(info.get("marketCap")),
                "beta": _safe(info.get("beta")),
                "fifty_two_week_high": _safe(info.get("fiftyTwoWeekHigh")),
                "fifty_two_week_low": _safe(info.get("fiftyTwoWeekLow")),
                "current_price": _safe(info.get("currentPrice") or info.get("regularMarketPrice")),
                "target_mean_price": _safe(info.get("targetMeanPrice")),
            }

            scores = _compute_scores(info)

            results[ticker] = {
                "metrics": metrics,
                "scores": scores,
                "info": {
                    "name": info.get("shortName", ticker),
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "exchange": info.get("exchange"),
                    "market_cap": metrics["market_cap"],
                },
            }

        except Exception as e:
            logger.warning(f"Failed to fetch fundamentals for {ticker}: {e}")

    return results


async def run_fundamental_backfill(start_date: str):
    """
    Fetch current fundamental snapshots for all active stocks.
    Creates one FundamentalSnapshot per ticker with today's date.
    """
    logger.info(f"Fundamental backfill starting")

    async with async_session() as session:
        stocks = await get_active_stocks(session)

    tickers = [s.Ticker for s in stocks]
    logger.info(f"Fetching fundamentals for {len(tickers)} tickers")

    if not tickers:
        raise RuntimeError("No active stocks found. Run price backfill first.")

    # Fetch in batches (yfinance is slow per-ticker, batch for progress tracking)
    batch_size = 20
    total_stored = 0
    total_failed = 0
    today = date.today()

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        logger.info(
            f"Fundamental batch {i // batch_size + 1}/{(len(tickers) + batch_size - 1) // batch_size}: "
            f"{len(batch)} tickers"
        )

        # Fetch from yfinance (blocking I/O)
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, _fetch_fundamentals_for_tickers, batch
        )

        # Store in database
        async with async_session() as session:
            for ticker, data in results.items():
                try:
                    stock = await get_or_create_stock(
                        session, ticker,
                        name=data["info"].get("name"),
                        sector=data["info"].get("sector"),
                        industry=data["info"].get("industry"),
                        exchange=data["info"].get("exchange"),
                        market_cap=data["info"].get("market_cap"),
                    )

                    snapshot = await insert_fundamental_snapshot(
                        session,
                        stock_id=stock.Id,
                        snapshot_date=today,
                        metrics=data["metrics"],
                        scores=data["scores"],
                    )

                    if snapshot:
                        total_stored += 1

                except Exception as e:
                    logger.error(f"Failed to store fundamentals for {ticker}: {e}")
                    total_failed += 1

            await session.commit()

    logger.info(
        f"Fundamental backfill complete: {total_stored} snapshots stored, {total_failed} failed"
    )
