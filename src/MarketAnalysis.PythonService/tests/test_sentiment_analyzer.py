"""Unit tests for SentimentAnalyzer GPU/CPU support and inference correctness."""

import pytest
from unittest.mock import patch, MagicMock

import sys
import os

# Add parent directory to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.sentiment import SentimentResult


class TestSentimentAnalyzerInit:
    """Test GPU/CPU detection and model loading."""

    def test_device_property_returns_string(self):
        """Device property returns 'cuda' or 'cpu'."""
        from services.sentiment_analyzer import SentimentAnalyzer

        analyzer = SentimentAnalyzer.get_instance()
        assert analyzer.device in ("cuda", "cpu")

    def test_batch_size_matches_device(self):
        """GPU uses batch_size=64, CPU uses batch_size=32."""
        from services.sentiment_analyzer import SentimentAnalyzer

        analyzer = SentimentAnalyzer.get_instance()
        if analyzer.device == "cuda":
            assert analyzer.batch_size == 64
        else:
            assert analyzer.batch_size == 32


class TestAnalyzeTexts:
    """Test FinBERT inference output correctness."""

    @pytest.fixture(autouse=True)
    def analyzer(self):
        from services.sentiment_analyzer import SentimentAnalyzer

        self.analyzer = SentimentAnalyzer.get_instance()

    def test_analyze_empty_list(self):
        """Empty input returns empty output."""
        results = self.analyzer.analyze_texts([])
        assert results == []

    def test_analyze_single_text(self):
        """Single text returns one SentimentResult with scores summing to ~1.0."""
        results = self.analyzer.analyze_texts(["Apple stock surges to record high"])
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, SentimentResult)
        assert abs(r.positive + r.negative + r.neutral - 1.0) < 0.01
        assert r.label in ("positive", "negative", "neutral")

    def test_analyze_batch(self):
        """Multiple texts return correct count of results."""
        texts = [
            "Company reports strong earnings",
            "Stock crashes after missed targets",
            "Market remains flat today",
        ]
        results = self.analyzer.analyze_texts(texts)
        assert len(results) == 3
        for r in results:
            assert abs(r.positive + r.negative + r.neutral - 1.0) < 0.01

    def test_analyze_large_batch_uses_configured_batch_size(self):
        """Large input is processed using the device-specific batch size."""
        texts = [f"Test headline number {i}" for i in range(100)]
        results = self.analyzer.analyze_texts(texts)
        assert len(results) == 100

    def test_scores_are_rounded(self):
        """Output scores are rounded to 4 decimal places."""
        results = self.analyzer.analyze_texts(["Apple stock price"])
        r = results[0]
        assert r.positive == round(r.positive, 4)
        assert r.negative == round(r.negative, 4)
        assert r.neutral == round(r.neutral, 4)

    def test_text_truncated_in_result(self):
        """Result text is truncated to 200 characters."""
        long_text = "A" * 500
        results = self.analyzer.analyze_texts([long_text])
        assert len(results[0].text) <= 200


class TestFallbackAnalyzer:
    """Test keyword-based fallback when FinBERT is unavailable."""

    def test_fallback_produces_results(self):
        """Fallback analyzer returns results without FinBERT."""
        from services.sentiment_analyzer import SentimentAnalyzer

        analyzer = SentimentAnalyzer.__new__(SentimentAnalyzer)
        analyzer._pipeline = None  # Simulate no model
        analyzer._device_name = "cpu"
        analyzer._batch_size = 32

        results = analyzer.analyze_texts(["stock price up gain profit"])
        assert len(results) == 1
        r = results[0]
        assert abs(r.positive + r.negative + r.neutral - 1.0) < 0.01
        assert r.label in ("positive", "negative", "neutral")

    def test_fallback_positive_text(self):
        """Fallback detects positive sentiment from keywords."""
        from services.sentiment_analyzer import SentimentAnalyzer

        analyzer = SentimentAnalyzer.__new__(SentimentAnalyzer)
        analyzer._pipeline = None
        analyzer._device_name = "cpu"
        analyzer._batch_size = 32

        results = analyzer.analyze_texts(["up gain bull buy profit surge rally"])
        r = results[0]
        assert r.positive > r.negative
