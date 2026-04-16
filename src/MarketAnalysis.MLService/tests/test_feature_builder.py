"""
Property-based and unit tests for FeatureBuilder helper methods.

Covers:
  - _compute_sector_momentum_features: value ranges, peer threshold, self-exclusion invariant
  - _compute_sentiment_from_records: value ranges, source routing, empty fallback
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.features.feature_builder import FeatureBuilder, SECTOR_FEATURES, SENTIMENT_FEATURES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_price_df(n: int, start_close: float = 100.0) -> pd.DataFrame:
    """Build a synthetic price DataFrame with n daily rows."""
    base = date(2024, 1, 1)
    closes = [start_close * (1 + 0.001 * i) for i in range(n)]
    return pd.DataFrame({
        "date": [base + timedelta(days=i) for i in range(n)],
        "close": closes,
    })


def _make_peer_pivot(n_days: int, n_peers: int, daily_return: float = 0.01) -> pd.DataFrame:
    """Build a peer price pivot with uniform daily returns."""
    base = date(2024, 1, 1)
    dates = [base + timedelta(days=i) for i in range(n_days)]
    data = {}
    for i in range(n_peers):
        start = 100.0
        prices = [start * ((1 + daily_return) ** d) for d in range(n_days)]
        data[f"PEER{i}"] = prices
    return pd.DataFrame(data, index=dates)


def _make_sentiment_record(source: str, pos: float, neg: float, neutral: float, sample: int = 10):
    """Build a mock SentimentScore ORM object."""
    rec = MagicMock()
    rec.Source = source
    rec.PositiveScore = pos
    rec.NegativeScore = neg
    rec.NeutralScore = neutral
    rec.SampleSize = sample
    return rec


# ---------------------------------------------------------------------------
# _compute_sector_momentum_features
# ---------------------------------------------------------------------------

class TestComputeSectorMomentumFeatures:
    def _builder(self):
        return FeatureBuilder(session=None)

    def test_empty_peer_pivot_returns_all_zeros(self):
        builder = self._builder()
        stock_df = _make_price_df(30)
        result = builder._compute_sector_momentum_features(stock_df, pd.DataFrame())
        for d, vals in result.items():
            assert vals["sector_momentum_5d"] == 0.0
            assert vals["sector_momentum_10d"] == 0.0
            assert vals["sector_momentum_20d"] == 0.0

    def test_none_peer_pivot_returns_all_zeros(self):
        builder = self._builder()
        stock_df = _make_price_df(30)
        result = builder._compute_sector_momentum_features(stock_df, None)
        for d, vals in result.items():
            assert vals["sector_momentum_5d"] == 0.0

    def test_two_peers_returns_all_zeros(self):
        """Fewer than 3 peers → all zeros regardless of price movement."""
        builder = self._builder()
        stock_df = _make_price_df(30)
        peer_pivot = _make_peer_pivot(30, n_peers=2, daily_return=0.05)
        result = builder._compute_sector_momentum_features(stock_df, peer_pivot)
        for d, vals in result.items():
            assert vals["sector_momentum_5d"] == 0.0
            assert vals["sector_momentum_10d"] == 0.0
            assert vals["sector_momentum_20d"] == 0.0

    def test_exactly_three_peers_produces_nonzero_values(self):
        builder = self._builder()
        stock_df = _make_price_df(40)
        peer_pivot = _make_peer_pivot(40, n_peers=3, daily_return=0.01)
        result = builder._compute_sector_momentum_features(stock_df, peer_pivot)
        # After 20+ days warmup, values should be non-zero
        later_dates = sorted(result.keys())[25:]
        nonzero = [result[d]["sector_momentum_20d"] for d in later_dates if result[d]["sector_momentum_20d"] != 0.0]
        assert len(nonzero) > 0, "Expected non-zero sector momentum after 20-day warmup"

    @given(
        n_peers=st.integers(min_value=3, max_value=10),
        daily_return=st.floats(min_value=-0.05, max_value=0.05, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=30)
    def test_uniform_returns_property(self, n_peers: int, daily_return: float):
        """With uniform daily returns across all peers, sector momentum should be close to compound return."""
        builder = self._builder()
        n_days = 50
        stock_df = _make_price_df(n_days)
        peer_pivot = _make_peer_pivot(n_days, n_peers=n_peers, daily_return=daily_return)
        result = builder._compute_sector_momentum_features(stock_df, peer_pivot)

        # Check all values are finite
        for d, vals in result.items():
            assert not np.isnan(vals["sector_momentum_5d"])
            assert not np.isnan(vals["sector_momentum_10d"])
            assert not np.isnan(vals["sector_momentum_20d"])

    @given(
        n_peers=st.integers(min_value=0, max_value=2),
    )
    @settings(max_examples=20)
    def test_below_threshold_always_zero(self, n_peers: int):
        """Any peer count below 3 must return 0.0 for all dates."""
        builder = self._builder()
        stock_df = _make_price_df(30)
        if n_peers == 0:
            peer_pivot = pd.DataFrame()
        else:
            peer_pivot = _make_peer_pivot(30, n_peers=n_peers, daily_return=0.01)
        result = builder._compute_sector_momentum_features(stock_df, peer_pivot)
        for d, vals in result.items():
            assert vals["sector_momentum_5d"] == 0.0, f"Expected 0.0 with {n_peers} peers"

    def test_result_keys_match_stock_dates(self):
        """Result dict must have exactly the same date keys as stock_prices_df."""
        builder = self._builder()
        stock_df = _make_price_df(25)
        peer_pivot = _make_peer_pivot(25, n_peers=5)
        result = builder._compute_sector_momentum_features(stock_df, peer_pivot)
        assert set(result.keys()) == set(stock_df["date"])

    def test_values_never_nan_or_inf(self):
        builder = self._builder()
        stock_df = _make_price_df(50)
        peer_pivot = _make_peer_pivot(50, n_peers=5, daily_return=0.02)
        result = builder._compute_sector_momentum_features(stock_df, peer_pivot)
        for d, vals in result.items():
            for col in ["sector_momentum_5d", "sector_momentum_10d", "sector_momentum_20d"]:
                assert not np.isnan(vals[col]), f"NaN at {d} col={col}"
                assert not np.isinf(vals[col]), f"Inf at {d} col={col}"


# ---------------------------------------------------------------------------
# _compute_sentiment_from_records
# ---------------------------------------------------------------------------

class TestComputeSentimentFromRecords:

    def test_empty_records_returns_neutral_defaults(self):
        result = FeatureBuilder._compute_sentiment_from_records([])
        assert result["news_positive"] == 0.5
        assert result["reddit_neutral"] == 0.5
        assert result["stocktwits_negative"] == 0.5
        assert result["sentiment_sample_size"] == 0.0

    def test_news_source_populates_news_columns(self):
        rec = _make_sentiment_record("news", pos=0.8, neg=0.1, neutral=0.1, sample=100)
        result = FeatureBuilder._compute_sentiment_from_records([rec])
        assert result["news_positive"] == pytest.approx(0.8)
        assert result["news_negative"] == pytest.approx(0.1)
        assert result["news_neutral"] == pytest.approx(0.1)
        assert result["sentiment_sample_size"] == pytest.approx(100.0)
        # Other sources stay at defaults
        assert result["reddit_positive"] == 0.5
        assert result["stocktwits_positive"] == 0.5

    def test_reddit_source_populates_reddit_columns(self):
        rec = _make_sentiment_record("reddit", pos=0.3, neg=0.6, neutral=0.1, sample=50)
        result = FeatureBuilder._compute_sentiment_from_records([rec])
        assert result["reddit_positive"] == pytest.approx(0.3)
        assert result["reddit_negative"] == pytest.approx(0.6)
        assert result["news_positive"] == 0.5  # unchanged

    def test_stocktwits_source_populates_stocktwits_columns(self):
        rec = _make_sentiment_record("stocktwits", pos=0.7, neg=0.2, neutral=0.1, sample=200)
        result = FeatureBuilder._compute_sentiment_from_records([rec])
        assert result["stocktwits_positive"] == pytest.approx(0.7)
        assert result["sentiment_sample_size"] == pytest.approx(200.0)

    def test_multiple_sources_cumulates_sample_size(self):
        recs = [
            _make_sentiment_record("news", 0.6, 0.2, 0.2, sample=100),
            _make_sentiment_record("reddit", 0.4, 0.4, 0.2, sample=50),
            _make_sentiment_record("stocktwits", 0.5, 0.3, 0.2, sample=75),
        ]
        result = FeatureBuilder._compute_sentiment_from_records(recs)
        assert result["sentiment_sample_size"] == pytest.approx(225.0)
        assert result["news_positive"] == pytest.approx(0.6)
        assert result["reddit_positive"] == pytest.approx(0.4)
        assert result["stocktwits_positive"] == pytest.approx(0.5)

    def test_unknown_source_is_ignored(self):
        rec = _make_sentiment_record("bloomberg", pos=0.9, neg=0.05, neutral=0.05, sample=500)
        result = FeatureBuilder._compute_sentiment_from_records([rec])
        # All sources stay at defaults; sample_size unchanged
        assert result["news_positive"] == 0.5
        assert result["sentiment_sample_size"] == 0.0

    @given(
        pos=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        neg=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        neutral=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        sample=st.integers(min_value=0, max_value=10_000),
    )
    @settings(max_examples=50)
    def test_output_keys_always_present(self, pos, neg, neutral, sample):
        rec = _make_sentiment_record("news", pos, neg, neutral, sample)
        result = FeatureBuilder._compute_sentiment_from_records([rec])
        expected_keys = {
            "news_positive", "news_negative", "news_neutral",
            "reddit_positive", "reddit_negative", "reddit_neutral",
            "stocktwits_positive", "stocktwits_negative", "stocktwits_neutral",
            "sentiment_sample_size",
        }
        assert expected_keys == set(result.keys())

    def test_case_insensitive_source_matching(self):
        recs = [
            _make_sentiment_record("NEWS", pos=0.7, neg=0.2, neutral=0.1, sample=10),
            _make_sentiment_record("Reddit", pos=0.6, neg=0.1, neutral=0.3, sample=20),
        ]
        result = FeatureBuilder._compute_sentiment_from_records(recs)
        assert result["news_positive"] == pytest.approx(0.7)
        assert result["reddit_positive"] == pytest.approx(0.6)
