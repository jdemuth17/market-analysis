"""
Read-only queries against the existing Market Analysis database.
"""
import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Stock, PriceHistory, TechnicalSignal, FundamentalSnapshot, SentimentScore,
)

logger = logging.getLogger(__name__)


async def get_active_stocks(session: AsyncSession) -> list[Stock]:
    result = await session.execute(
        select(Stock).where(Stock.IsActive == True).order_by(Stock.Ticker)
    )
    return list(result.scalars().all())


async def get_stocks_by_tickers(session: AsyncSession, tickers: list[str]) -> list[Stock]:
    result = await session.execute(
        select(Stock).where(Stock.Ticker.in_(tickers))
    )
    return list(result.scalars().all())


async def get_price_history(
    session: AsyncSession,
    stock_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 365,
) -> list[PriceHistory]:
    query = select(PriceHistory).where(PriceHistory.StockId == stock_id)
    if start_date:
        query = query.where(PriceHistory.Date >= start_date)
    if end_date:
        query = query.where(PriceHistory.Date <= end_date)
    query = query.order_by(PriceHistory.Date.desc()).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_price_history_df(
    session: AsyncSession,
    stock_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 365,
) -> pd.DataFrame:
    rows = await get_price_history(session, stock_id, start_date, end_date, limit)
    if not rows:
        return pd.DataFrame()
    data = [
        {
            "date": r.Date,
            "open": float(r.Open),
            "high": float(r.High),
            "low": float(r.Low),
            "close": float(r.Close),
            "adj_close": float(r.AdjClose) if r.AdjClose else float(r.Close),
            "volume": int(r.Volume),
        }
        for r in rows
    ]
    df = pd.DataFrame(data).sort_values("date").reset_index(drop=True)
    return df


async def get_technical_signals(
    session: AsyncSession,
    stock_id: int,
    since_date: Optional[date] = None,
) -> list[TechnicalSignal]:
    query = select(TechnicalSignal).where(TechnicalSignal.StockId == stock_id)
    if since_date:
        query = query.where(TechnicalSignal.DetectedDate >= since_date)
    query = query.order_by(TechnicalSignal.DetectedDate.desc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_latest_fundamental(
    session: AsyncSession,
    stock_id: int,
    as_of_date: Optional[date] = None,
) -> Optional[FundamentalSnapshot]:
    query = select(FundamentalSnapshot).where(
        FundamentalSnapshot.StockId == stock_id
    )
    if as_of_date:
        query = query.where(FundamentalSnapshot.SnapshotDate <= as_of_date)
    query = query.order_by(FundamentalSnapshot.SnapshotDate.desc()).limit(1)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_latest_sentiment(
    session: AsyncSession,
    stock_id: int,
    as_of_date: Optional[date] = None,
) -> list[SentimentScore]:
    """Get the most recent sentiment scores across all sources."""
    if not as_of_date:
        as_of_date = date.today()

    # Get the most recent analysis date within the last 7 days
    since = as_of_date - timedelta(days=7)
    query = select(SentimentScore).where(
        and_(
            SentimentScore.StockId == stock_id,
            SentimentScore.AnalysisDate >= since,
            SentimentScore.AnalysisDate <= as_of_date,
        )
    ).order_by(SentimentScore.AnalysisDate.desc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_stock_count(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count(Stock.Id)).where(Stock.IsActive == True)
    )
    return result.scalar_one()


async def get_price_date_range(
    session: AsyncSession,
    stock_id: int,
) -> tuple[Optional[date], Optional[date]]:
    """Get the earliest and latest price dates for a stock."""
    result = await session.execute(
        select(
            func.min(PriceHistory.Date),
            func.max(PriceHistory.Date),
        ).where(PriceHistory.StockId == stock_id)
    )
    row = result.one()
    return row[0], row[1]


# --- Batch Queries for ML Scoring ---

async def get_batch_price_history(
    session: AsyncSession,
    stock_ids: list[int],
    start_date: date,
    end_date: date,
) -> dict[int, list[PriceHistory]]:
    """Fetch price history for multiple stocks in one query."""
    query = select(PriceHistory).where(
        and_(
            PriceHistory.StockId.in_(stock_ids),
            PriceHistory.Date >= start_date,
            PriceHistory.Date <= end_date,
        )
    ).order_by(PriceHistory.StockId, PriceHistory.Date.desc())
    
    result = await session.execute(query)
    rows = list(result.scalars().all())
    
    mapping: dict[int, list[PriceHistory]] = {sid: [] for sid in stock_ids}
    for r in rows:
        mapping[r.StockId].append(r)
    return mapping


async def get_batch_technical_signals(
    session: AsyncSession,
    stock_ids: list[int],
    since_date: date,
) -> dict[int, list[TechnicalSignal]]:
    """Fetch technical signals for multiple stocks in one query."""
    query = select(TechnicalSignal).where(
        and_(
            TechnicalSignal.StockId.in_(stock_ids),
            TechnicalSignal.DetectedDate >= since_date,
        )
    ).order_by(TechnicalSignal.StockId, TechnicalSignal.DetectedDate.desc())
    
    result = await session.execute(query)
    rows = list(result.scalars().all())
    
    mapping: dict[int, list[TechnicalSignal]] = {sid: [] for sid in stock_ids}
    for r in rows:
        mapping[r.StockId].append(r)
    return mapping


async def get_batch_latest_fundamentals(
    session: AsyncSession,
    stock_ids: list[int],
    as_of_date: date,
) -> dict[int, Optional[FundamentalSnapshot]]:
    """Fetch the single most recent fundamental snapshot for multiple stocks."""
    # Use a subquery to find the max date per stock_id
    subq = select(
        FundamentalSnapshot.StockId,
        func.max(FundamentalSnapshot.SnapshotDate).label("max_date")
    ).where(
        and_(
            FundamentalSnapshot.StockId.in_(stock_ids),
            FundamentalSnapshot.SnapshotDate <= as_of_date,
        )
    ).group_by(FundamentalSnapshot.StockId).subquery()

    query = select(FundamentalSnapshot).join(
        subq,
        and_(
            FundamentalSnapshot.StockId == subq.c.StockId,
            FundamentalSnapshot.SnapshotDate == subq.c.max_date
        )
    )
    
    result = await session.execute(query)
    rows = list(result.scalars().all())
    
    mapping: dict[int, Optional[FundamentalSnapshot]] = {sid: None for sid in stock_ids}
    for r in rows:
        mapping[r.StockId] = r
    return mapping


async def get_batch_latest_sentiment(
    session: AsyncSession,
    stock_ids: list[int],
    as_of_date: date,
) -> dict[int, list[SentimentScore]]:
    """Fetch recent sentiment scores for multiple stocks in one query."""
    since = as_of_date - timedelta(days=7)
    query = select(SentimentScore).where(
        and_(
            SentimentScore.StockId.in_(stock_ids),
            SentimentScore.AnalysisDate >= since,
            SentimentScore.AnalysisDate <= as_of_date,
        )
    ).order_by(SentimentScore.StockId, SentimentScore.AnalysisDate.desc())
    
    result = await session.execute(query)
    rows = list(result.scalars().all())
    
    mapping: dict[int, list[SentimentScore]] = {sid: [] for sid in stock_ids}
    for r in rows:
        mapping[r.StockId].append(r)
    return mapping
