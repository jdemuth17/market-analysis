"""
Mock integration tests for label_generator sentiment and sector momentum backfill.

Tests verify correct population of sentiment columns and sector momentum
columns when the DB returns known data, using in-memory mocks (no DB required).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.features.feature_builder import FeatureBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sentiment_record(source: str, pos: float, neg: float, neutral: float,
                            analysis_date: date = date(2024, 6, 1), sample: int = 10):
    rec = MagicMock()
    rec.Source = source
    rec.PositiveScore = pos
    rec.NegativeScore = neg
    rec.NeutralScore = neutral
    rec.SampleSize = sample
    rec.AnalysisDate = analysis_date
    return rec


def _build_minimal_price_df(n: int = 250) -> pd.DataFrame:
    base = date(2023, 1, 1)
    return pd.DataFrame({
        "date":  [base + timedelta(days=i) for i in range(n)],
        "close": [100.0 + i * 0.1 for i in range(n)],
        "open":  [100.0] * n,
        "high":  [101.0] * n,
        "low":   [99.0] * n,
        "volume": [1_000_000] * n,
    })


# ---------------------------------------------------------------------------
# Sentiment backfill logic tests
# ---------------------------------------------------------------------------

class TestSentimentBackfill:
    """
    Validate that _compute_sentiment_from_records integrates correctly with
    the date-based lookup logic expected in label_generator backfill.
    """

    def test_no_records_all_neutral(self):
        result = FeatureBuilder._compute_sentiment_from_records([])
        assert result["news_positive"] == 0.5
        assert result["reddit_positive"] == 0.5
        assert result["stocktwits_positive"] == 0.5
        assert result["sentiment_sample_size"] == 0.0

    def test_single_news_record_populates_news_columns_only(self):
        rec = _make_sentiment_record("news", pos=0.75, neg=0.15, neutral=0.10, sample=50)
        result = FeatureBuilder._compute_sentiment_from_records([rec])
        assert result["news_positive"] == pytest.approx(0.75)
        assert result["news_negative"] == pytest.approx(0.15)
        assert result["reddit_positive"] == 0.5   # unchanged
        assert result["stocktwits_positive"] == 0.5  # unchanged
        assert result["sentiment_sample_size"] == pytest.approx(50.0)

    def test_three_sources_all_populated(self):
        recs = [
            _make_sentiment_record("news", 0.6, 0.2, 0.2, sample=100),
            _make_sentiment_record("reddit", 0.4, 0.4, 0.2, sample=80),
            _make_sentiment_record("stocktwits", 0.55, 0.3, 0.15, sample=60),
        ]
        result = FeatureBuilder._compute_sentiment_from_records(recs)
        assert result["news_positive"] == pytest.approx(0.6)
        assert result["reddit_positive"] == pytest.approx(0.4)
        assert result["stocktwits_positive"] == pytest.approx(0.55)
        assert result["sentiment_sample_size"] == pytest.approx(240.0)

    @given(
        sources=st.lists(
            st.sampled_from(["news", "reddit", "stocktwits"]),
            min_size=1, max_size=3, unique=True,
        ),
        pos=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=40)
    def test_sentiment_values_always_in_range(self, sources, pos):
        """Property: all output score values stay in [0, 1]."""
        recs = [_make_sentiment_record(s, pos, 1 - pos, 0.0, sample=1) for s in sources]
        result = FeatureBuilder._compute_sentiment_from_records(recs)
        score_keys = [k for k in result if k != "sentiment_sample_size"]
        for key in score_keys:
            assert 0.0 <= result[key] <= 1.0, f"{key}={result[key]} out of range"


# ---------------------------------------------------------------------------
# Sector momentum backfill logic tests
# ---------------------------------------------------------------------------

class TestSectorMomentumBackfill:
    """Unit tests for _compute_sector_momentum_features used by label_generator."""

    def _builder(self):
        return FeatureBuilder(session=None)

    def _make_peer_pivot(self, n_days: int, n_peers: int, daily_return: float = 0.01):
        base = date(2024, 1, 1)
        dates = [base + timedelta(days=i) for i in range(n_days)]
        data = {}
        for i in range(n_peers):
            prices = [100.0 * ((1 + daily_return) ** d) for d in range(n_days)]
            data[f"PEER{i}"] = prices
        return pd.DataFrame(data, index=dates)

    def _make_stock_df(self, n: int):
        base = date(2024, 1, 1)
        return pd.DataFrame({
            "date": [base + timedelta(days=i) for i in range(n)],
            "close": [100.0] * n,
        })

    def test_null_sector_returns_zeros(self):
        builder = self._builder()
        stock_df = self._make_stock_df(30)
        result = builder._compute_sector_momentum_features(stock_df, None)
        for d, vals in result.items():
            assert vals["sector_momentum_5d"] == 0.0

    def test_two_peers_below_threshold_returns_zeros(self):
        builder = self._builder()
        stock_df = self._make_stock_df(30)
        peer_pivot = self._make_peer_pivot(30, n_peers=2, daily_return=0.02)
        result = builder._compute_sector_momentum_features(stock_df, peer_pivot)
        for d, vals in result.items():
            assert vals["sector_momentum_5d"] == 0.0
            assert vals["sector_momentum_10d"] == 0.0
            assert vals["sector_momentum_20d"] == 0.0

    def test_five_peers_uniform_return_nonzero_after_warmup(self):
        """With 5 peers all gaining 1%/day, 20-day return should be ≈20.2% after warmup."""
        builder = self._builder()
        n = 50
        stock_df = self._make_stock_df(n)
        peer_pivot = self._make_peer_pivot(n, n_peers=5, daily_return=0.01)
        result = builder._compute_sector_momentum_features(stock_df, peer_pivot)
        # Day 25+ should have valid 20d momentum ≈ (1.01)^20 - 1 ≈ 0.2202
        day_25 = sorted(result.keys())[25]
        mom = result[day_25]["sector_momentum_20d"]
        assert mom == pytest.approx((1.01 ** 20) - 1, rel=0.01)

    def test_output_never_nan(self):
        builder = self._builder()
        stock_df = self._make_stock_df(40)
        peer_pivot = self._make_peer_pivot(40, n_peers=4)
        result = builder._compute_sector_momentum_features(stock_df, peer_pivot)
        for d, vals in result.items():
            for col in ["sector_momentum_5d", "sector_momentum_10d", "sector_momentum_20d"]:
                assert not np.isnan(vals[col])
                assert not np.isinf(vals[col])

    @given(
        n_peers=st.integers(min_value=0, max_value=2),
    )
    @settings(max_examples=10)
    def test_property_below_3_peers_always_zero(self, n_peers):
        builder = self._builder()
        stock_df = self._make_stock_df(30)
        if n_peers == 0:
            pivot = pd.DataFrame()
        else:
            pivot = self._make_peer_pivot(30, n_peers=n_peers)
        result = builder._compute_sector_momentum_features(stock_df, pivot)
        for d, vals in result.items():
            assert vals["sector_momentum_5d"] == 0.0

    def test_date_keys_match_stock_df(self):
        """All dates from stock_df must appear as keys in result."""
        builder = self._builder()
        stock_df = self._make_stock_df(25)
        peer_pivot = self._make_peer_pivot(25, n_peers=5)
        result = builder._compute_sector_momentum_features(stock_df, peer_pivot)
        assert set(result.keys()) == set(stock_df["date"])
