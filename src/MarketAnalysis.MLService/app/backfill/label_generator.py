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
    FUNDAMENTAL_FEATURES, SENTIMENT_FEATURES,
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
                df.at[idx, "revenue_growth"] = float(f.RevenueGrowth) if f.RevenueGrowth else 0
                df.at[idx, "earnings_growth"] = float(f.EarningsGrowth) if f.EarningsGrowth else 0
                df.at[idx, "beta"] = float(f.Beta) if f.Beta else 1.0
                df.at[idx, "dividend_yield"] = float(f.DividendYield) if f.DividendYield else 0
                df.at[idx, "value_score"] = (float(f.ValueScore) / 100.0) if f.ValueScore else 0.5
                df.at[idx, "quality_score"] = (float(f.QualityScore) / 100.0) if f.QualityScore else 0.5
                df.at[idx, "growth_score"] = (float(f.GrowthScore) / 100.0) if f.GrowthScore else 0.5
                df.at[idx, "safety_score"] = (float(f.SafetyScore) / 100.0) if f.SafetyScore else 0.5

    # Add sentiment features (default neutral 0.5)
    for col in SENTIMENT_FEATURES:
        if "sample_size" in col:
            df[col] = 0.0
        else:
            df[col] = 0.5

    # Sentiment is not available for historical backfill — stays at neutral defaults

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

    logger.info(f"Building training data for {len(stocks)} stocks")

    all_frames = []
    processed = 0
    skipped = 0

    for idx, stock in enumerate(stocks):
        try:
            df = await _build_dataset_for_stock(stock.Id, stock.Ticker)
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
