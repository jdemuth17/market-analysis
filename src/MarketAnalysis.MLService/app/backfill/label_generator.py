"""
Label generation and training dataset export.

Reads PriceHistory from the database, computes forward returns at multiple
horizons, generates binary labels per category, builds the full feature matrix
using vectorized computations, and exports to parquet for fast training.
"""
import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select, func

from app.config import settings
from app.db.connection import async_session
from app.db.models import Stock, PriceHistory, TechnicalSignal, FundamentalSnapshot, SentimentScore
from app.db.queries import get_active_stocks
from app.features.feature_builder import (
    FeatureBuilder, ALL_FEATURES, TECHNICAL_FEATURES,
    FUNDAMENTAL_FEATURES, SENTIMENT_FEATURES, SECTOR_FEATURES,
)

logger = logging.getLogger(__name__)

# Label thresholds
LABEL_CONFIG = {
    "daytrade": {"horizon": 1, "threshold": 0.02},       # 1 day, >2%
    "swingtrade": {"horizon": 5, "threshold": 0.05},      # 5 days, >5%
    "shorttermhold": {"horizon": 10, "threshold": 0.08},   # 10 days, >8%
    "longtermhold": {"horizon": 30, "threshold": 0.15},    # 30 days, >15%
}

EXPORT_DIR = Path("training_data")


def _compute_forward_returns(prices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute forward returns at 1, 5, 10, 30 day horizons.
    Input: DataFrame with columns [date, close] sorted by date ascending.
    Output: DataFrame with return_Xd and label_category columns.
    """
    df = prices_df.copy()
    close = df["close"]

    for horizon in [1, 5, 10, 30]:
        df[f"return_{horizon}d"] = close.shift(-horizon) / close - 1

    # Generate binary labels
    for category, cfg in LABEL_CONFIG.items():
        horizon = cfg["horizon"]
        threshold = cfg["threshold"]
        df[f"label_{category}"] = (df[f"return_{horizon}d"] > threshold).astype(float)
        # Set NaN for rows where we can't compute forward returns
        df.loc[df[f"return_{horizon}d"].isna(), f"label_{category}"] = np.nan

    return df


async def _precompute_sector_momentum(
    session,
    stocks: list,
) -> dict:
    """
    Precompute sector momentum for all stocks before the per-stock loop.

    Returns: {sector: {ticker: pd.DataFrame(index=date, columns=[sector_momentum_5d/10d/20d])}}
    Each ticker's DataFrame uses only peer prices (self excluded) to avoid circular dependency.
    Only sectors with at least 3 total stocks produce entries; others are absent (caller falls back to 0.0).
    """
    logger.info("Precomputing sector momentum for all stocks")

    stock_map = {s.Id: (s.Ticker, s.Sector) for s in stocks}
    stock_ids = list(stock_map.keys())

    # Single batch query for all prices (full history for SMA200 depth)
    result = await session.execute(
        select(PriceHistory.StockId, PriceHistory.Date, PriceHistory.Close)
        .where(PriceHistory.StockId.in_(stock_ids))
        .order_by(PriceHistory.StockId, PriceHistory.Date)
    )
    all_prices = result.all()
    logger.info(f"Loaded {len(all_prices)} price rows for sector momentum precomputation")

    # Build flat records with sector annotation
    price_records = []
    for stock_id, date_val, close_val in all_prices:
        ticker, sector = stock_map.get(stock_id, (None, None))
        if ticker and sector:
            price_records.append({
                "date": date_val,
                "ticker": ticker,
                "sector": sector,
                "close": float(close_val),
            })

    if not price_records:
        return {}

    all_df = pd.DataFrame(price_records)
    sectors = all_df["sector"].dropna().unique()
    sector_momentum_map: dict[str, dict[str, pd.DataFrame]] = {}

    for sector in sectors:
        sector_df = all_df[all_df["sector"] == sector]
        tickers = sector_df["ticker"].unique()

        if len(tickers) < 3:
            # Too few tickers in sector to produce a valid average
            continue

        # Pivot: rows=date, cols=ticker, values=close
        pivot = sector_df.pivot(index="date", columns="ticker", values="close").sort_index()

        sector_momentum_map[sector] = {}
        for ticker in tickers:
            peer_cols = [t for t in tickers if t != ticker]
            if len(peer_cols) < 3:
                # After self-exclusion fewer than 3 peers remain → all zeros
                sector_momentum_map[sector][ticker] = pd.DataFrame(
                    {"sector_momentum_5d": 0.0, "sector_momentum_10d": 0.0, "sector_momentum_20d": 0.0},
                    index=pivot.index,
                )
            else:
                peers = pivot[peer_cols]
                ret_5d  = (peers / peers.shift(5)  - 1).mean(axis=1).fillna(0.0)
                ret_10d = (peers / peers.shift(10) - 1).mean(axis=1).fillna(0.0)
                ret_20d = (peers / peers.shift(20) - 1).mean(axis=1).fillna(0.0)
                sector_momentum_map[sector][ticker] = pd.DataFrame({
                    "sector_momentum_5d":  ret_5d,
                    "sector_momentum_10d": ret_10d,
                    "sector_momentum_20d": ret_20d,
                })

    logger.info(f"Sector momentum precomputed for {len(sector_momentum_map)} sectors")
    return sector_momentum_map


def _compute_vectorized_technical_features(prices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all technical indicator features for every row in the price DataFrame.
    Vectorized — no per-row loops.
    """
    df = prices_df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi_14"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    df["macd_signal"] = signal
    df["macd_histogram"] = macd - signal

    # SMA ratios
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    df["sma20_sma50_ratio"] = sma20 / sma50.replace(0, np.nan)
    df["sma50_sma200_ratio"] = sma50 / sma200.replace(0, np.nan)

    # Bollinger Bands %B
    bb_std = close.rolling(20).std()
    bb_upper = sma20 + 2 * bb_std
    bb_lower = sma20 - 2 * bb_std
    bb_range = bb_upper - bb_lower
    df["bollinger_pct_b"] = (close - bb_lower) / bb_range.replace(0, np.nan)

    # ADX (simplified)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    plus_dm = (high - high.shift()).clip(lower=0)
    minus_dm = (low.shift() - low).clip(lower=0)
    plus_di = 100 * (plus_dm.rolling(14).mean() / atr14.replace(0, np.nan))
    minus_di = 100 * (minus_dm.rolling(14).mean() / atr14.replace(0, np.nan))
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    df["adx"] = dx.rolling(14).mean()

    # ATR normalized
    df["atr_normalized"] = atr14 / close.replace(0, np.nan)

    # Stochastic
    low14 = low.rolling(14).min()
    high14 = high.rolling(14).max()
    stoch_k = 100 * (close - low14) / (high14 - low14).replace(0, np.nan)
    df["stoch_k"] = stoch_k
    df["stoch_d"] = stoch_k.rolling(3).mean()

    # OBV slope (5-day)
    obv = (np.sign(close.diff()) * volume).cumsum()
    df["obv_slope_5d"] = (obv - obv.shift(5)) / 5

    # Volume ratio
    vol_avg = volume.rolling(20).mean()
    df["volume_ratio_20d"] = volume / vol_avg.replace(0, np.nan)

    # Pattern features default to 0 (filled from TechnicalSignal table separately)
    df["best_pattern_confidence"] = 0.0
    df["best_pattern_direction"] = 0.0
    df["num_active_patterns"] = 0.0
    df["days_since_pattern"] = 60.0

    return df


async def _build_dataset_for_stock(
    stock_id: int,
    ticker: str,
    sentiment_records: list,
    sector: str | None,
    sector_momentum_map: dict,
) -> pd.DataFrame | None:
    """Build complete feature + label DataFrame for one stock."""
    async with async_session() as session:
        # Get prices
        result = await session.execute(
            select(PriceHistory)
            .where(PriceHistory.StockId == stock_id)
            .order_by(PriceHistory.Date)
        )
        prices = result.scalars().all()

    if len(prices) < 250:  # Need at least ~1 year for SMA200
        return None

    # Build price DataFrame
    pdf = pd.DataFrame([{
        "date": p.Date,
        "open": float(p.Open),
        "high": float(p.High),
        "low": float(p.Low),
        "close": float(p.Close),
        "adj_close": float(p.AdjClose) if p.AdjClose else float(p.Close),
        "volume": int(p.Volume),
    } for p in prices]).sort_values("date").reset_index(drop=True)

    # Compute technical indicators (vectorized)
    df = _compute_vectorized_technical_features(pdf)

    # Compute forward returns and labels
    df = _compute_forward_returns(df)

    # Add pattern features from TechnicalSignal table
    async with async_session() as session:
        result = await session.execute(
            select(TechnicalSignal)
            .where(TechnicalSignal.StockId == stock_id)
            .order_by(TechnicalSignal.DetectedDate)
        )
        signals = result.scalars().all()

    if signals:
        # Build a lookup: date -> best signal
        signal_dates = {}
        for s in signals:
            d = s.DetectedDate
            if d not in signal_dates or s.Confidence > signal_dates[d]["confidence"]:
                direction_map = {"Bullish": 1.0, "Bearish": -1.0, "Neutral": 0.0}
                signal_dates[d] = {
                    "confidence": s.Confidence / 100.0,
                    "direction": direction_map.get(s.Direction, 0.0),
                }

        for idx, row in df.iterrows():
            row_date = row["date"]
            # Find most recent signal within 60 days
            best_conf = 0
            best_dir = 0
            days_since = 60
            count = 0
            for s in signals:
                if s.DetectedDate <= row_date:
                    gap = (row_date - s.DetectedDate).days
                    if gap <= 60:
                        count += 1
                        if s.Confidence / 100.0 > best_conf:
                            best_conf = s.Confidence / 100.0
                            direction_map = {"Bullish": 1.0, "Bearish": -1.0, "Neutral": 0.0}
                            best_dir = direction_map.get(s.Direction, 0.0)
                            days_since = gap

            df.at[idx, "best_pattern_confidence"] = best_conf
            df.at[idx, "best_pattern_direction"] = best_dir
            df.at[idx, "num_active_patterns"] = float(count)
            df.at[idx, "days_since_pattern"] = float(days_since)

    # Add fundamental features (forward-filled from most recent snapshot)
    async with async_session() as session:
        result = await session.execute(
            select(FundamentalSnapshot)
            .where(FundamentalSnapshot.StockId == stock_id)
            .order_by(FundamentalSnapshot.SnapshotDate)
        )
        fundamentals = result.scalars().all()

    # Initialize fundamental columns with defaults
    for col in FUNDAMENTAL_FEATURES:
        df[col] = 0.0

    if fundamentals:
        # Forward-fill: each snapshot applies until the next one
        fund_idx = 0
        for idx, row in df.iterrows():
            # Advance to most recent snapshot before/on this date
            while (fund_idx < len(fundamentals) - 1 and
                   fundamentals[fund_idx + 1].SnapshotDate <= row["date"]):
                fund_idx += 1

            if fundamentals[fund_idx].SnapshotDate <= row["date"]:
                f = fundamentals[fund_idx]
                mcap = float(f.MarketCap) if f.MarketCap else 0
                df.at[idx, "pe_ratio"] = float(f.PeRatio) if f.PeRatio else 0
                df.at[idx, "forward_pe"] = float(f.ForwardPe) if f.ForwardPe else 0
                df.at[idx, "peg_ratio"] = float(f.PegRatio) if f.PegRatio else 0
                df.at[idx, "price_to_book"] = float(f.PriceToBook) if f.PriceToBook else 0
                df.at[idx, "profit_margin"] = float(f.ProfitMargin) if f.ProfitMargin else 0
                df.at[idx, "operating_margin"] = float(f.OperatingMargin) if f.OperatingMargin else 0
                df.at[idx, "roe"] = float(f.ReturnOnEquity) if f.ReturnOnEquity else 0
                df.at[idx, "debt_to_equity"] = float(f.DebtToEquity) if f.DebtToEquity else 0
                fcf = float(f.FreeCashFlow) if f.FreeCashFlow else 0
                df.at[idx, "fcf_to_mcap"] = fcf / mcap if mcap > 0 else 0
                df.at[idx, "revenue_per_share"] = float(f.RevenuePerShare) if f.RevenuePerShare else 0
                df.at[idx, "earnings_per_share"] = float(f.EarningsPerShare) if f.EarningsPerShare else 0
                df.at[idx, "beta"] = float(f.Beta) if f.Beta else 1.0
                df.at[idx, "dividend_yield"] = float(f.DividendYield) if f.DividendYield else 0
                df.at[idx, "value_score"] = (float(f.ValueScore) / 100.0) if f.ValueScore else 0.5
                df.at[idx, "quality_score"] = (float(f.QualityScore) / 100.0) if f.QualityScore else 0.5
                df.at[idx, "growth_score"] = (float(f.GrowthScore) / 100.0) if f.GrowthScore else 0.5
                df.at[idx, "safety_score"] = (float(f.SafetyScore) / 100.0) if f.SafetyScore else 0.5

    # Add sentiment features — backfill from pre-fetched records (90-day forward-fill)
    # Build lookup: date -> list of SentimentScore records on that date
    sentiment_by_date: dict = {}
    for s in sentiment_records:
        sentiment_by_date.setdefault(s.AnalysisDate, []).append(s)

    # Initialize all sentiment columns with neutral defaults
    for col in SENTIMENT_FEATURES:
        df[col] = 0.0 if "sample_size" in col else 0.5

    sorted_sentiment_dates = sorted(sentiment_by_date.keys(), reverse=True)
    for idx, row in df.iterrows():
        row_date = row["date"]
        lookback_start = row_date - timedelta(days=90)
        # Find most recent sentiment date within the 90-day window
        recent_records = []
        for sd in sorted_sentiment_dates:
            if sd > row_date:
                continue
            if sd < lookback_start:
                break
            recent_records = sentiment_by_date[sd]
            break  # Take only the most recent date within window

        if recent_records:
            sent_features = FeatureBuilder._compute_sentiment_from_records(recent_records)
            for col, val in sent_features.items():
                df.at[idx, col] = val

    # Add sector momentum features from precomputed map
    if sector and sector in sector_momentum_map and ticker in sector_momentum_map[sector]:
        momentum_df = sector_momentum_map[sector][ticker]
        df = df.merge(momentum_df, left_on="date", right_index=True, how="left")
        df["sector_momentum_5d"]  = df["sector_momentum_5d"].fillna(0.0)
        df["sector_momentum_10d"] = df["sector_momentum_10d"].fillna(0.0)
        df["sector_momentum_20d"] = df["sector_momentum_20d"].fillna(0.0)
    else:
        df["sector_momentum_5d"]  = 0.0
        df["sector_momentum_10d"] = 0.0
        df["sector_momentum_20d"] = 0.0

    # Add metadata
    df["stock_id"] = stock_id
    df["ticker"] = ticker

    # Keep only rows where SMA200 is valid (need 200+ days warm-up)
    df = df.iloc[200:].reset_index(drop=True)

    # Select final columns
    label_cols = [
        "return_1d", "return_5d", "return_10d", "return_30d",
        "label_daytrade", "label_swingtrade", "label_shorttermhold", "label_longtermhold",
    ]
    meta_cols = ["stock_id", "ticker", "date"]
    output_cols = meta_cols + ALL_FEATURES + label_cols
    df = df[[c for c in output_cols if c in df.columns]]

    # Clean inf/nan in features
    for col in ALL_FEATURES:
        if col in df.columns:
            df[col] = df[col].replace([np.inf, -np.inf], 0.0).fillna(0.0)

    return df


async def run_label_generation():
    """
    Build the full training dataset for all active stocks.
    Exports to parquet files in training_data/ directory.
    """
    logger.info("Label generation and training dataset export starting")

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    async with async_session() as session:
        stocks = await get_active_stocks(session)

        # Batch-load all sentiment records for all active stocks in one query
        stock_ids = [s.Id for s in stocks]
        logger.info(f"Batch-loading sentiment records for {len(stock_ids)} stocks")
        sent_result = await session.execute(
            select(SentimentScore)
            .where(SentimentScore.StockId.in_(stock_ids))
            .order_by(SentimentScore.StockId, SentimentScore.AnalysisDate)
        )
        all_sentiment_records = sent_result.scalars().all()
        sentiment_map: dict[int, list] = {sid: [] for sid in stock_ids}
        for rec in all_sentiment_records:
            sentiment_map[rec.StockId].append(rec)
        logger.info(f"Loaded {len(all_sentiment_records)} sentiment records")

        # Precompute sector momentum for all stocks before per-stock loop
        sector_momentum_map = await _precompute_sector_momentum(session, stocks)

    logger.info(f"Building training data for {len(stocks)} stocks")

    all_frames = []
    processed = 0
    skipped = 0

    for idx, stock in enumerate(stocks):
        try:
            df = await _build_dataset_for_stock(
                stock.Id,
                stock.Ticker,
                sentiment_map[stock.Id],
                stock.Sector,
                sector_momentum_map,
            )
            if df is not None and len(df) > 0:
                all_frames.append(df)
                processed += 1
            else:
                skipped += 1
        except Exception as e:
            logger.error(f"Failed to build dataset for {stock.Ticker}: {e}")
            skipped += 1

        if (idx + 1) % 100 == 0:
            logger.info(f"Progress: {idx + 1}/{len(stocks)} stocks processed")

    if not all_frames:
        raise RuntimeError("No training data generated. Check that price backfill ran first.")

    # Combine all stocks
    full_dataset = pd.concat(all_frames, ignore_index=True)

    # Sort by date for proper time-ordered splits
    full_dataset = full_dataset.sort_values(["date", "ticker"]).reset_index(drop=True)

    # Export
    parquet_path = EXPORT_DIR / "training_dataset.parquet"
    full_dataset.to_parquet(parquet_path, index=False)

    # Also export summary stats
    stats = {
        "total_rows": len(full_dataset),
        "total_stocks": processed,
        "skipped_stocks": skipped,
        "date_range": f"{full_dataset['date'].min()} to {full_dataset['date'].max()}",
        "features": len(ALL_FEATURES),
        "label_positive_rates": {},
    }
    for cat in LABEL_CONFIG:
        col = f"label_{cat}"
        if col in full_dataset.columns:
            valid = full_dataset[col].dropna()
            stats["label_positive_rates"][cat] = f"{valid.mean():.3f} ({int(valid.sum())}/{len(valid)})"

    logger.info(f"Training dataset exported to {parquet_path}")
    logger.info(f"Stats: {stats}")

    # Save stats
    import json
    stats_path = EXPORT_DIR / "dataset_stats.json"
    # Convert date objects for JSON
    stats["date_range"] = str(stats["date_range"])
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2, default=str)

    logger.info(
        f"Label generation complete: {len(full_dataset)} rows, "
        f"{processed} stocks, exported to {parquet_path}"
    )
