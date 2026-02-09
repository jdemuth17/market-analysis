"""
Write operations for backfill pipeline.
Handles upsert logic for PriceHistory, FundamentalSnapshot, TechnicalSignal, and Stock.
"""
import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select, and_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Stock, PriceHistory, FundamentalSnapshot, TechnicalSignal

logger = logging.getLogger(__name__)


async def get_or_create_stock(
    session: AsyncSession,
    ticker: str,
    name: Optional[str] = None,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    exchange: Optional[str] = None,
    market_cap: Optional[float] = None,
) -> Stock:
    """Get existing stock by ticker or create a new one."""
    result = await session.execute(
        select(Stock).where(Stock.Ticker == ticker)
    )
    stock = result.scalar_one_or_none()

    if stock:
        # Update fields if provided
        if name and not stock.Name:
            stock.Name = name
        if sector and not stock.Sector:
            stock.Sector = sector
        if industry and not stock.Industry:
            stock.Industry = industry
        if exchange and not stock.Exchange:
            stock.Exchange = exchange
        if market_cap:
            stock.MarketCap = market_cap
        stock.LastUpdatedUtc = datetime.utcnow()
        await session.flush()
        return stock

    stock = Stock(
        Ticker=ticker,
        Name=name or ticker,
        Sector=sector,
        Industry=industry,
        Exchange=exchange,
        MarketCap=market_cap,
        IsActive=True,
        LastUpdatedUtc=datetime.utcnow(),
    )
    session.add(stock)
    await session.flush()
    return stock


async def upsert_price_history_batch(
    session: AsyncSession,
    stock_id: int,
    rows: list[dict],
) -> int:
    """
    Batch upsert price history rows. Uses PostgreSQL ON CONFLICT for efficiency.
    Each row dict should have: date, open, high, low, close, adj_close, volume.
    Returns number of rows upserted.
    """
    if not rows:
        return 0

    values = []
    for r in rows:
        values.append({
            "StockId": stock_id,
            "Date": r["date"],
            "Open": r["open"],
            "High": r["high"],
            "Low": r["low"],
            "Close": r["close"],
            "AdjClose": r.get("adj_close", r["close"]),
            "Volume": r["volume"],
        })

    stmt = pg_insert(PriceHistory).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["StockId", "Date"],
        set_={
            "Open": stmt.excluded.Open,
            "High": stmt.excluded.High,
            "Low": stmt.excluded.Low,
            "Close": stmt.excluded.Close,
            "AdjClose": stmt.excluded.AdjClose,
            "Volume": stmt.excluded.Volume,
        },
    )
    await session.execute(stmt)
    return len(values)


async def insert_fundamental_snapshot(
    session: AsyncSession,
    stock_id: int,
    snapshot_date: date,
    metrics: dict,
    scores: dict,
    raw_data: Optional[dict] = None,
) -> FundamentalSnapshot:
    """Insert a fundamental snapshot. Skips if one already exists for this stock+date."""
    existing = await session.execute(
        select(FundamentalSnapshot).where(
            and_(
                FundamentalSnapshot.StockId == stock_id,
                FundamentalSnapshot.SnapshotDate == snapshot_date,
            )
        )
    )
    if existing.scalar_one_or_none():
        return None  # Already exists

    snapshot = FundamentalSnapshot(
        StockId=stock_id,
        SnapshotDate=snapshot_date,
        PeRatio=metrics.get("pe_ratio"),
        ForwardPe=metrics.get("forward_pe"),
        PegRatio=metrics.get("peg_ratio"),
        PriceToBook=metrics.get("price_to_book"),
        DebtToEquity=metrics.get("debt_to_equity"),
        ProfitMargin=metrics.get("profit_margin"),
        OperatingMargin=metrics.get("operating_margin"),
        ReturnOnEquity=metrics.get("roe"),
        FreeCashFlow=metrics.get("free_cash_flow"),
        DividendYield=metrics.get("dividend_yield"),
        Revenue=metrics.get("revenue"),
        RevenueGrowth=metrics.get("revenue_growth"),
        EarningsGrowth=metrics.get("earnings_growth"),
        EpsTrailingTwelveMonths=metrics.get("eps"),
        MarketCap=metrics.get("market_cap"),
        Beta=metrics.get("beta"),
        FiftyTwoWeekHigh=metrics.get("fifty_two_week_high"),
        FiftyTwoWeekLow=metrics.get("fifty_two_week_low"),
        CurrentPrice=metrics.get("current_price"),
        TargetMeanPrice=metrics.get("target_mean_price"),
        ValueScore=scores.get("value_score", 0),
        QualityScore=scores.get("quality_score", 0),
        GrowthScore=scores.get("growth_score", 0),
        SafetyScore=scores.get("safety_score", 0),
        CompositeScore=scores.get("composite_score", 0),
        RawData=raw_data,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def insert_technical_signal(
    session: AsyncSession,
    stock_id: int,
    detected_date: date,
    pattern_type: str,
    direction: str,
    confidence: float,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: str = "confirmed",
    key_price_levels: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> TechnicalSignal:
    """Insert a technical signal. Skips if duplicate (same stock, date, pattern)."""
    existing = await session.execute(
        select(TechnicalSignal).where(
            and_(
                TechnicalSignal.StockId == stock_id,
                TechnicalSignal.DetectedDate == detected_date,
                TechnicalSignal.PatternType == pattern_type,
            )
        )
    )
    if existing.scalar_one_or_none():
        return None

    signal = TechnicalSignal(
        StockId=stock_id,
        DetectedDate=detected_date,
        PatternType=pattern_type,
        Direction=direction,
        Confidence=confidence,
        StartDate=start_date,
        EndDate=end_date,
        Status=status,
        KeyPriceLevels=key_price_levels,
        Metadata=metadata,
    )
    session.add(signal)
    await session.flush()
    return signal
