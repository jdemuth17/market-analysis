"""
Builds 46-feature vectors from raw database data for XGBoost (snapshot)
and sequence-length sequences for LSTM (temporal).
"""
import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select

import numpy as np
import pandas as pd
import pandas_ta as ta
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import queries
from app.db.models import Stock

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

SECTOR_FEATURES = [
    "sector_momentum_5d",
    "sector_momentum_10d",
    "sector_momentum_20d",
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

ALL_FEATURES = TECHNICAL_FEATURES + FUNDAMENTAL_FEATURES + SENTIMENT_FEATURES + SECTOR_FEATURES


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
        results = await self.build_batch_snapshots([stock_id], as_of_date)
        return results.get(stock_id)

    async def build_batch_snapshots(
        self,
        stock_ids: list[int],
        as_of_date: date,
    ) -> dict[int, pd.DataFrame]:
        """
        Build 46-feature rows for multiple stocks in optimized bulk queries.
        Returns a mapping of stock_id -> 1-row DataFrame.
        """
        if not stock_ids:
            return {}

        # 1. Fetch all data in bulk queries (one query per data type)
        price_start = as_of_date - timedelta(days=300)
        batch_prices = await queries.get_batch_price_history(
            self.session, stock_ids, start_date=price_start, end_date=as_of_date
        )
        batch_signals = await queries.get_batch_technical_signals(
            self.session, stock_ids, since_date=as_of_date - timedelta(days=60)
        )
        batch_fundamentals = await queries.get_batch_latest_fundamentals(
            self.session, stock_ids, as_of_date=as_of_date
        )
        batch_sentiments = await queries.get_batch_latest_sentiment(
            self.session, stock_ids, as_of_date=as_of_date
        )

        # Fetch stock records to get Sector for sector momentum
        stock_result = await self.session.execute(
            select(Stock).where(Stock.Id.in_(stock_ids))
        )
        stock_records = {s.Id: s for s in stock_result.scalars().all()}

        # Precompute sector peer price pivots (one batch query for all sectors)
        sector_peers = await self._fetch_sector_peer_prices(stock_records, as_of_date)

        # 2. Process each stock
        results: dict[int, pd.DataFrame] = {}
        for sid in stock_ids:
            prices_list = batch_prices.get(sid, [])
            if len(prices_list) < 50:
                continue

            data = [
                {
                    "date": r.Date,
                    "open": float(r.Open),
                    "high": float(r.High),
                    "low": float(r.Low),
                    "close": float(r.Close),
                    "volume": int(r.Volume),
                }
                for r in prices_list
            ]
            prices_df = pd.DataFrame(data).sort_values("date").reset_index(drop=True)

            features = {}
            features.update(self._compute_technical_indicators(prices_df))
            features.update(self._compute_pattern_features(batch_signals.get(sid, []), as_of_date))
            features.update(self._compute_fundamental_features(batch_fundamentals.get(sid), prices_df))
            features.update(self._compute_sentiment_features(batch_sentiments.get(sid, [])))

            # Sector momentum (0.0 fallback when sector NULL or <3 peers)
            stock = stock_records.get(sid)
            peer_pivot = (
                sector_peers.get(stock.Sector, {}).get(stock.Ticker)
                if stock and stock.Sector else None
            )
            momentum_by_date = self._compute_sector_momentum_features(prices_df, peer_pivot)
            latest_date = prices_df["date"].iloc[-1]
            features.update(
                momentum_by_date.get(
                    latest_date,
                    {"sector_momentum_5d": 0.0, "sector_momentum_10d": 0.0, "sector_momentum_20d": 0.0},
                )
            )

            # Build 1-row DataFrame
            row = {col: features.get(col, 0.0) for col in ALL_FEATURES}
            df = pd.DataFrame([row], columns=ALL_FEATURES)
            df = df.replace([np.inf, -np.inf], 0.0).fillna(0.0)
            results[sid] = df

        return results

    async def _fetch_sector_peer_prices(
        self,
        stock_records: dict,
        as_of_date: date,
    ) -> dict:
        """
        Fetch close prices for all sector peers and return pivoted DataFrames.
        Returns: {sector: {ticker: peer_pivot_df}}
        peer_pivot_df has columns=peer_tickers (self excluded), index=date.
        Only sectors with at least 3 total stocks are included.
        """
        # Group stocks by sector
        sector_tickers: dict[str, list[tuple[int, str]]] = {}
        for sid, stock in stock_records.items():
            if stock.Sector:
                sector_tickers.setdefault(stock.Sector, []).append((sid, stock.Ticker))

        if not sector_tickers:
            return {}

        # Single batch price query for all stocks covering 300-day lookback
        # (300d = SMA200 minimum + 100 day safety margin for gaps)
        all_peer_ids = [sid for pairs in sector_tickers.values() for sid, _ in pairs]
        price_start = as_of_date - timedelta(days=300)
        batch_prices = await queries.get_batch_price_history(
            self.session, all_peer_ids, start_date=price_start, end_date=as_of_date
        )

        result: dict[str, dict[str, pd.DataFrame]] = {}
        for sector, stock_list in sector_tickers.items():
            if len(stock_list) < 3:
                continue

            # Build sector-wide price records
            records = []
            for sid, ticker in stock_list:
                for p in batch_prices.get(sid, []):
                    records.append({"date": p.Date, "ticker": ticker, "close": float(p.Close)})

            if not records:
                continue

            pivot = (
                pd.DataFrame(records)
                .pivot(index="date", columns="ticker", values="close")
                .sort_index()
            )

            # Build per-ticker peer pivot (self-excluded)
            result[sector] = {}
            for _, ticker in stock_list:
                peer_cols = [t for t in pivot.columns if t != ticker]
                result[sector][ticker] = pivot[peer_cols] if len(peer_cols) >= 3 else pd.DataFrame()

        return result

    async def build_sequence(
        self,
        stock_id: int,
        as_of_date: date,
    ) -> Optional[pd.DataFrame]:
        """
        Build a sequence of 46-feature vectors for LSTM.
        Returns a (seq_len, 46) DataFrame or None if insufficient data.
        """
        seq_len = settings.lstm_sequence_length
        # Need extra days for indicator warm-up (SMA200 requires 200 days minimum)
        start = as_of_date - timedelta(days=seq_len + 250)

        prices = await queries.get_price_history_df(
            self.session, stock_id,
            start_date=start,
            end_date=as_of_date,
            limit=500,
        )
        if len(prices) < seq_len + 200:
            return None

        # Fetch stock record for sector momentum
        stock_result = await self.session.execute(
            select(Stock).where(Stock.Id == stock_id)
        )
        stock = stock_result.scalar_one_or_none()

        # Precompute sector peer pivot covering the full sequence window
        peer_pivot: Optional[pd.DataFrame] = None
        if stock and stock.Sector:
            sector_peers = await self._fetch_sector_peer_prices({stock_id: stock}, as_of_date)
            peer_pivot = sector_peers.get(stock.Sector, {}).get(stock.Ticker)

        # Precompute sector momentum dict keyed by date (one call over full price range)
        sector_momentum_by_date = self._compute_sector_momentum_features(prices, peer_pivot)

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

            # Sentiment
            sentiments = await queries.get_latest_sentiment(
                self.session, stock_id, day
            )
            features.update(self._compute_sentiment_features(sentiments))

            # Sector momentum (precomputed, no extra DB query)
            features.update(
                sector_momentum_by_date.get(
                    day,
                    {"sector_momentum_5d": 0.0, "sector_momentum_10d": 0.0, "sector_momentum_20d": 0.0},
                )
            )

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
        """Compute technical indicators from OHLCV DataFrame using pandas-ta."""
        features = {}
        if len(prices) < 20:
            return features

        # RSI(14)
        rsi = prices.ta.rsi(length=14)
        features["rsi_14"] = float(rsi.iloc[-1]) if rsi is not None and not rsi.empty else 50.0

        # MACD(12, 26, 9)
        macd = prices.ta.macd()
        if macd is not None and not macd.empty:
            # columns: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
            features["macd_signal"] = float(macd.iloc[-1, 2])
            features["macd_histogram"] = float(macd.iloc[-1, 1])
        else:
            features["macd_signal"] = 0.0
            features["macd_histogram"] = 0.0

        # SMA ratios
        sma20 = prices.ta.sma(length=20)
        sma50 = prices.ta.sma(length=50)
        sma200 = prices.ta.sma(length=200)
        
        features["sma20_sma50_ratio"] = (
            float(sma20.iloc[-1] / sma50.iloc[-1])
            if sma20 is not None and sma50 is not None and sma50.iloc[-1] != 0 else 1.0
        )
        features["sma50_sma200_ratio"] = (
            float(sma50.iloc[-1] / sma200.iloc[-1])
            if sma50 is not None and sma200 is not None and sma200.iloc[-1] != 0 else 1.0
        )

        # Bollinger Bands %B
        bbands = prices.ta.bbands(length=20, std=2)
        if bbands is not None and not bbands.empty:
            # columns: BBL_20_2.0, BBM_20_2.0, BBU_20_2.0, BBB_20_2.0, BBP_20_2.0
            features["bollinger_pct_b"] = float(bbands.iloc[-1, 4])
        else:
            features["bollinger_pct_b"] = 0.5

        # ADX
        adx = prices.ta.adx(length=14)
        if adx is not None and not adx.empty:
            # columns: ADX_14, DMP_14, DMN_14
            features["adx"] = float(adx.iloc[-1, 0])
        else:
            features["adx"] = 25.0

        # ATR normalized by price
        atr = prices.ta.atr(length=14)
        features["atr_normalized"] = (
            float(atr.iloc[-1] / prices["close"].iloc[-1])
            if atr is not None and not atr.empty and prices["close"].iloc[-1] != 0 else 0.0
        )

        # Stochastic
        stoch = prices.ta.stoch(k=14, d=3)
        if stoch is not None and not stoch.empty:
            # columns: STOCHk_14_3_3, STOCHd_14_3_3
            features["stoch_k"] = float(stoch.iloc[-1, 0])
            features["stoch_d"] = float(stoch.iloc[-1, 1])
        else:
            features["stoch_k"] = 50.0
            features["stoch_d"] = 50.0

        # OBV slope (5-day)
        obv = prices.ta.obv()
        if obv is not None and len(obv) >= 5:
            obv_slope = (obv.iloc[-1] - obv.iloc[-5]) / 5
            features["obv_slope_5d"] = float(obv_slope)
        else:
            features["obv_slope_5d"] = 0.0

        # Volume ratio (today vs 20-day average)
        vol_sma = prices.ta.sma(close=prices["volume"], length=20)
        features["volume_ratio_20d"] = (
            float(prices["volume"].iloc[-1] / vol_sma.iloc[-1])
            if vol_sma is not None and vol_sma.iloc[-1] != 0 else 1.0
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
    def _compute_sentiment_from_records(records: list) -> dict:
        """
        Extract sentiment feature values from pre-fetched SentimentScore ORM objects.
        Used by label_generator for in-memory backfill (avoids per-row DB queries).
        Mirrors _compute_sentiment_features() but accepts an already-fetched list.
        """
        features = {
            "news_positive": 0.5, "news_negative": 0.5, "news_neutral": 0.5,
            "reddit_positive": 0.5, "reddit_negative": 0.5, "reddit_neutral": 0.5,
            "stocktwits_positive": 0.5, "stocktwits_negative": 0.5, "stocktwits_neutral": 0.5,
            "sentiment_sample_size": 0.0,
        }
        if not records:
            return features

        total_samples = 0
        for s in records:
            source = s.Source.lower() if s.Source else ""
            if source in ("news", "reddit", "stocktwits"):
                features[f"{source}_positive"] = float(s.PositiveScore)
                features[f"{source}_negative"] = float(s.NegativeScore)
                features[f"{source}_neutral"] = float(s.NeutralScore)
                total_samples += s.SampleSize

        features["sentiment_sample_size"] = float(total_samples)
        return features

    def _compute_sector_momentum_features(
        self,
        stock_prices_df: pd.DataFrame,
        peer_prices_pivot: pd.DataFrame,
    ) -> dict:
        """
        Compute sector momentum for each date in stock_prices_df.

        peer_prices_pivot: DataFrame with columns=peer_tickers, index=date, values=close.
        Self-exclusion is the caller's responsibility (pass peers only, not self).

        Returns: {date: {sector_momentum_5d: float, sector_momentum_10d: float, sector_momentum_20d: float}}
        Falls back to 0.0 per column when fewer than 3 peers or date absent from pivot.
        """
        zero = {"sector_momentum_5d": 0.0, "sector_momentum_10d": 0.0, "sector_momentum_20d": 0.0}

        # Require at least 3 distinct peer tickers
        if peer_prices_pivot is None or peer_prices_pivot.empty or len(peer_prices_pivot.columns) < 3:
            return {d: dict(zero) for d in stock_prices_df["date"]}

        # Vectorized N-day returns across all peer tickers
        avg_5d  = (peer_prices_pivot / peer_prices_pivot.shift(5)  - 1).mean(axis=1)
        avg_10d = (peer_prices_pivot / peer_prices_pivot.shift(10) - 1).mean(axis=1)
        avg_20d = (peer_prices_pivot / peer_prices_pivot.shift(20) - 1).mean(axis=1)

        result = {}
        for d in stock_prices_df["date"]:
            if d in avg_5d.index:
                result[d] = {
                    "sector_momentum_5d":  float(avg_5d.at[d])  if pd.notna(avg_5d.at[d])  else 0.0,
                    "sector_momentum_10d": float(avg_10d.at[d]) if pd.notna(avg_10d.at[d]) else 0.0,
                    "sector_momentum_20d": float(avg_20d.at[d]) if pd.notna(avg_20d.at[d]) else 0.0,
                }
            else:
                result[d] = dict(zero)
        return result

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            v = float(value)
            return default if np.isinf(v) or np.isnan(v) else v
        except (TypeError, ValueError):
            return default
