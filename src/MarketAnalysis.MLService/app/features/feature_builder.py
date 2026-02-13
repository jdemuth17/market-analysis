"""
Builds 45-feature vectors from raw database data for XGBoost (snapshot)
and 60-day sequences for LSTM (temporal).
"""
import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import queries

logger = logging.getLogger(__name__)

# Feature column names (45 total)
TECHNICAL_FEATURES = [
    "rsi_14",
    "macd_signal",
    "macd_histogram",
    "sma20_sma50_ratio",
    "sma50_sma200_ratio",
    "bollinger_pct_b",
    "adx",
    "atr_normalized",
    "stoch_k",
    "stoch_d",
    "obv_slope_5d",
    "volume_ratio_20d",
    "best_pattern_confidence",
    "best_pattern_direction",
    "num_active_patterns",
    "days_since_pattern",
]

FUNDAMENTAL_FEATURES = [
    "pe_ratio",
    "forward_pe",
    "peg_ratio",
    "price_to_book",
    "profit_margin",
    "operating_margin",
    "roe",
    "debt_to_equity",
    "fcf_to_mcap",
    "revenue_per_share",
    "earnings_per_share",
    "beta",
    "dividend_yield",
    "value_score",
    "quality_score",
    "growth_score",
    "safety_score",
]

SENTIMENT_FEATURES = [
    "news_positive",
    "news_negative",
    "news_neutral",
    "reddit_positive",
    "reddit_negative",
    "reddit_neutral",
    "stocktwits_positive",
    "stocktwits_negative",
    "stocktwits_neutral",
    "sentiment_sample_size",
]

# Not included in total but used for labels
LABEL_COLUMNS = [
    "label_daytrade",       # 1-day return > 2%
    "label_swingtrade",     # 5-day return > 5%
    "label_shorttermhold",  # 10-day return > 8%
    "label_longtermhold",   # 30-day return > 15%
    "return_1d",
    "return_5d",
    "return_10d",
    "return_30d",
]

ALL_FEATURES = TECHNICAL_FEATURES + FUNDAMENTAL_FEATURES + SENTIMENT_FEATURES


class FeatureBuilder:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def build_snapshot(
        self,
        stock_id: int,
        as_of_date: date,
    ) -> Optional[pd.DataFrame]:
        """
        Build a single 45-feature row for XGBoost prediction.
        Returns a 1-row DataFrame or None if insufficient data.
        """
        features = {}

        # --- Technical features from price history ---
        prices = await queries.get_price_history_df(
            self.session, stock_id,
            start_date=as_of_date - timedelta(days=300),
            end_date=as_of_date,
            limit=250,
        )
        if len(prices) < 50:
            return None

        tech = self._compute_technical_indicators(prices)
        features.update(tech)

        # --- Pattern features from TechnicalSignal ---
        signals = await queries.get_technical_signals(
            self.session, stock_id,
            since_date=as_of_date - timedelta(days=60),
        )
        features.update(self._compute_pattern_features(signals, as_of_date))

        # --- Fundamental features ---
        fundamental = await queries.get_latest_fundamental(
            self.session, stock_id, as_of_date
        )
        features.update(self._compute_fundamental_features(fundamental, prices))

        # --- Sentiment features ---
        sentiments = await queries.get_latest_sentiment(
            self.session, stock_id, as_of_date
        )
        features.update(self._compute_sentiment_features(sentiments))

        # Build DataFrame with consistent column order
        row = {col: features.get(col, 0.0) for col in ALL_FEATURES}
        df = pd.DataFrame([row], columns=ALL_FEATURES)

        # Replace inf/nan with 0
        df = df.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        return df

    async def build_sequence(
        self,
        stock_id: int,
        as_of_date: date,
    ) -> Optional[pd.DataFrame]:
        """
        Build a 60-day sequence of 45-feature vectors for LSTM.
        Returns a (60, 45) DataFrame or None if insufficient data.
        """
        seq_len = settings.lstm_sequence_length
        # Need extra days for indicator warm-up
        start = as_of_date - timedelta(days=seq_len + 250)

        prices = await queries.get_price_history_df(
            self.session, stock_id,
            start_date=start,
            end_date=as_of_date,
            limit=500,
        )
        if len(prices) < seq_len + 200:
            return None

        # Build features for each trading day in the sequence window
        rows = []
        trading_days = prices["date"].tolist()
        # Take the last seq_len trading days
        target_days = trading_days[-seq_len:]

        for day in target_days:
            # Slice prices up to this day
            day_prices = prices[prices["date"] <= day].tail(250)
            if len(day_prices) < 50:
                continue

            features = {}
            tech = self._compute_technical_indicators(day_prices)
            features.update(tech)

            # Pattern features (simplified for sequences - use cached if available)
            signals = await queries.get_technical_signals(
                self.session, stock_id,
                since_date=day - timedelta(days=60),
            )
            # Filter to signals before or on this day
            day_signals = [s for s in signals if s.DetectedDate <= day]
            features.update(self._compute_pattern_features(day_signals, day))

            # Fundamentals (forward-filled from most recent snapshot)
            fundamental = await queries.get_latest_fundamental(
                self.session, stock_id, day
            )
            features.update(self._compute_fundamental_features(fundamental, day_prices))

            # Sentiment (use neutral for historical if not available)
            sentiments = await queries.get_latest_sentiment(
                self.session, stock_id, day
            )
            features.update(self._compute_sentiment_features(sentiments))

            row = {col: features.get(col, 0.0) for col in ALL_FEATURES}
            rows.append(row)

        if len(rows) < seq_len:
            return None

        df = pd.DataFrame(rows[-seq_len:], columns=ALL_FEATURES)
        df = df.replace([np.inf, -np.inf], 0.0).fillna(0.0)

        # Z-score normalize per column within the sequence
        mean = df.mean()
        std = df.std().replace(0, 1)
        df = (df - mean) / std

        return df

    async def build_training_dataset(
        self,
        session: AsyncSession,
    ) -> Optional[pd.DataFrame]:
        """
        Build the full training dataset for XGBoost.
        Returns a DataFrame with ALL_FEATURES + LABEL_COLUMNS.
        Placeholder — will be fully implemented in Phase 2 (backfill).
        """
        logger.warning("build_training_dataset not yet implemented (requires backfill)")
        return None

    def _compute_technical_indicators(self, prices: pd.DataFrame) -> dict:
        """Compute technical indicators from OHLCV DataFrame."""
        features = {}
        close = prices["close"]
        high = prices["high"]
        low = prices["low"]
        volume = prices["volume"]

        # RSI(14)
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        features["rsi_14"] = float(rsi.iloc[-1]) if not rsi.empty else 50.0

        # MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        histogram = macd - signal
        features["macd_signal"] = float(signal.iloc[-1]) if not signal.empty else 0.0
        features["macd_histogram"] = float(histogram.iloc[-1]) if not histogram.empty else 0.0

        # SMA ratios
        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        features["sma20_sma50_ratio"] = (
            float(sma20.iloc[-1] / sma50.iloc[-1])
            if not sma50.empty and sma50.iloc[-1] != 0 else 1.0
        )
        features["sma50_sma200_ratio"] = (
            float(sma50.iloc[-1] / sma200.iloc[-1])
            if len(prices) >= 200 and not sma200.empty and sma200.iloc[-1] != 0 else 1.0
        )

        # Bollinger Bands %B
        bb_mid = sma20
        bb_std = close.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_range = bb_upper - bb_lower
        pct_b = (close - bb_lower) / bb_range.replace(0, np.nan)
        features["bollinger_pct_b"] = float(pct_b.iloc[-1]) if not pct_b.empty else 0.5

        # ADX (simplified)
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()
        # Simplified ADX approximation using directional movement
        plus_dm = (high - high.shift()).clip(lower=0)
        minus_dm = (low.shift() - low).clip(lower=0)
        plus_di = 100 * (plus_dm.rolling(14).mean() / atr14.replace(0, np.nan))
        minus_di = 100 * (minus_dm.rolling(14).mean() / atr14.replace(0, np.nan))
        dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
        adx = dx.rolling(14).mean()
        features["adx"] = float(adx.iloc[-1]) if not adx.empty else 25.0

        # ATR normalized by price
        features["atr_normalized"] = (
            float(atr14.iloc[-1] / close.iloc[-1])
            if not atr14.empty and close.iloc[-1] != 0 else 0.0
        )

        # Stochastic
        low14 = low.rolling(14).min()
        high14 = high.rolling(14).max()
        stoch_k = 100 * (close - low14) / (high14 - low14).replace(0, np.nan)
        stoch_d = stoch_k.rolling(3).mean()
        features["stoch_k"] = float(stoch_k.iloc[-1]) if not stoch_k.empty else 50.0
        features["stoch_d"] = float(stoch_d.iloc[-1]) if not stoch_d.empty else 50.0

        # OBV slope (5-day)
        obv = (np.sign(close.diff()) * volume).cumsum()
        if len(obv) >= 5:
            obv_slope = (obv.iloc[-1] - obv.iloc[-5]) / 5
            features["obv_slope_5d"] = float(obv_slope)
        else:
            features["obv_slope_5d"] = 0.0

        # Volume ratio (today vs 20-day average)
        vol_avg = volume.rolling(20).mean()
        features["volume_ratio_20d"] = (
            float(volume.iloc[-1] / vol_avg.iloc[-1])
            if not vol_avg.empty and vol_avg.iloc[-1] != 0 else 1.0
        )

        return features

    def _compute_pattern_features(
        self, signals: list, as_of_date: date
    ) -> dict:
        """Extract pattern features from TechnicalSignal records."""
        features = {
            "best_pattern_confidence": 0.0,
            "best_pattern_direction": 0.0,  # -1 bearish, 0 neutral, 1 bullish
            "num_active_patterns": 0,
            "days_since_pattern": 60.0,  # default: no recent pattern
        }

        if not signals:
            return features

        # Active/recent patterns
        active = [s for s in signals if s.Status in ("forming", "confirmed", "active")]
        features["num_active_patterns"] = len(active)

        # Best confidence
        if signals:
            best = max(signals, key=lambda s: s.Confidence)
            features["best_pattern_confidence"] = float(best.Confidence) / 100.0

            direction_map = {"Bullish": 1.0, "Bearish": -1.0, "Neutral": 0.0}
            features["best_pattern_direction"] = direction_map.get(best.Direction, 0.0)

            days = (as_of_date - best.DetectedDate).days
            features["days_since_pattern"] = min(float(days), 60.0)

        return features

    def _compute_fundamental_features(
        self,
        fundamental: Optional[object],
        prices: pd.DataFrame,
    ) -> dict:
        """Extract fundamental features from FundamentalSnapshot."""
        defaults = {f: 0.0 for f in FUNDAMENTAL_FEATURES}

        if fundamental is None:
            return defaults

        last_close = float(prices["close"].iloc[-1]) if len(prices) > 0 else 0

        features = {
            "pe_ratio": self._safe_float(fundamental.PeRatio, 0.0),
            "forward_pe": self._safe_float(fundamental.ForwardPe, 0.0),
            "peg_ratio": self._safe_float(fundamental.PegRatio, 0.0),
            "price_to_book": self._safe_float(fundamental.PriceToBook, 0.0),
            "profit_margin": self._safe_float(fundamental.ProfitMargin, 0.0),
            "operating_margin": self._safe_float(fundamental.OperatingMargin, 0.0),
            "roe": self._safe_float(fundamental.ReturnOnEquity, 0.0),
            "debt_to_equity": self._safe_float(fundamental.DebtToEquity, 0.0),
            "revenue_per_share": self._safe_float(fundamental.RevenuePerShare, 0.0),
            "earnings_per_share": self._safe_float(fundamental.EarningsPerShare, 0.0),
            "beta": self._safe_float(fundamental.Beta, 1.0),
            "dividend_yield": self._safe_float(fundamental.DividendYield, 0.0),
            "value_score": self._safe_float(fundamental.ValueScore, 50.0) / 100.0,
            "quality_score": self._safe_float(fundamental.QualityScore, 50.0) / 100.0,
            "growth_score": self._safe_float(fundamental.GrowthScore, 50.0) / 100.0,
            "safety_score": self._safe_float(fundamental.SafetyScore, 50.0) / 100.0,
        }

        # FCF / Market Cap ratio
        fcf = self._safe_float(fundamental.FreeCashFlow, 0.0)
        mcap = self._safe_float(fundamental.MarketCap, 0.0)
        features["fcf_to_mcap"] = fcf / mcap if mcap > 0 else 0.0

        return features

    def _compute_sentiment_features(self, sentiments: list) -> dict:
        """Extract sentiment features from SentimentScore records."""
        features = {f: 0.5 if "positive" in f or "negative" in f or "neutral" in f else 0.0
                    for f in SENTIMENT_FEATURES}
        # Default neutral (0.5) for score fields, 0 for sample size
        features["sentiment_sample_size"] = 0.0
        features["news_positive"] = 0.5
        features["news_negative"] = 0.5
        features["news_neutral"] = 0.5
        features["reddit_positive"] = 0.5
        features["reddit_negative"] = 0.5
        features["reddit_neutral"] = 0.5
        features["stocktwits_positive"] = 0.5
        features["stocktwits_negative"] = 0.5
        features["stocktwits_neutral"] = 0.5

        if not sentiments:
            return features

        total_samples = 0
        for s in sentiments:
            source = s.Source.lower() if s.Source else ""
            if source == "news":
                prefix = "news"
            elif source == "reddit":
                prefix = "reddit"
            elif source == "stocktwits":
                prefix = "stocktwits"
            else:
                continue

            features[f"{prefix}_positive"] = float(s.PositiveScore)
            features[f"{prefix}_negative"] = float(s.NegativeScore)
            features[f"{prefix}_neutral"] = float(s.NeutralScore)
            total_samples += s.SampleSize

        features["sentiment_sample_size"] = float(total_samples)
        return features

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            v = float(value)
            return default if np.isinf(v) or np.isnan(v) else v
        except (TypeError, ValueError):
            return default
