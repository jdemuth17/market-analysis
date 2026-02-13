"""Integration tests for the sentiment router's full pipeline endpoint."""

import pytest
import time
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from models.sentiment import SentimentSource, SentimentText


client = TestClient(app)


def _mock_news_scraper(ticker, max_items=30):
    """Returns fake news texts for testing."""
    return [
        SentimentText(source=SentimentSource.NEWS, text=f"{ticker} stock news headline {i}")
        for i in range(min(3, max_items))
    ]


def _mock_reddit_scraper(ticker, max_items=30):
    """Returns fake reddit texts for testing."""
    return [
        SentimentText(source=SentimentSource.REDDIT, text=f"{ticker} reddit post {i}")
        for i in range(min(2, max_items))
    ]


def _mock_stocktwits_scraper(ticker, max_items=30):
    """Returns fake stocktwits texts for testing."""
    return [
        SentimentText(source=SentimentSource.STOCKTWITS, text=f"{ticker} stocktwit {i}")
        for i in range(min(2, max_items))
    ]


class TestFullPipeline:
    """Integration tests for /api/sentiment/full-pipeline."""

    @patch("routers.sentiment.news_scraper")
    @patch("routers.sentiment.reddit_scraper")
    def test_full_pipeline_returns_valid_response(self, mock_reddit, mock_news):
        """Pipeline returns TickerSentiment structure with valid scores."""
        mock_news.fetch_news = _mock_news_scraper
        mock_reddit.fetch_posts = _mock_reddit_scraper

        response = client.post("/api/sentiment/full-pipeline", json={
            "tickers": ["AAPL"],
            "sources": ["news", "reddit"],
            "max_items_per_source": 5,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["total_tickers"] == 1
        assert data["total_texts_analyzed"] > 0
        assert len(data["data"]) > 0

        for item in data["data"]:
            assert item["ticker"] == "AAPL"
            assert item["source"] in ("news", "reddit")
            assert 0 <= item["positive_score"] <= 1
            assert 0 <= item["negative_score"] <= 1
            assert item["sample_size"] > 0

    @patch("routers.sentiment.news_scraper")
    @patch("routers.sentiment.reddit_scraper")
    def test_full_pipeline_handles_scraper_error(self, mock_reddit, mock_news):
        """One ticker failing collection doesn't block others."""
        def news_fail(ticker, max_items=30):
            if ticker == "FAIL":
                raise Exception("Simulated scraper failure")
            return _mock_news_scraper(ticker, max_items)

        mock_news.fetch_news = news_fail
        mock_reddit.fetch_posts = _mock_reddit_scraper

        response = client.post("/api/sentiment/full-pipeline", json={
            "tickers": ["AAPL", "FAIL", "MSFT"],
            "sources": ["news", "reddit"],
            "max_items_per_source": 5,
        })

        assert response.status_code == 200
        data = response.json()
        # AAPL and MSFT should have results; FAIL may have partial (reddit still works)
        tickers_in_response = {item["ticker"] for item in data["data"]}
        assert "AAPL" in tickers_in_response
        assert "MSFT" in tickers_in_response

    def test_full_pipeline_empty_tickers(self):
        """Empty ticker list returns empty response."""
        response = client.post("/api/sentiment/full-pipeline", json={
            "tickers": [],
            "sources": ["news"],
            "max_items_per_source": 5,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["total_tickers"] == 0
        assert data["total_texts_analyzed"] == 0
        assert data["data"] == []

    @patch("routers.sentiment.news_scraper")
    @patch("routers.sentiment.reddit_scraper")
    def test_parallel_collection_faster_than_sequential(self, mock_reddit, mock_news):
        """5 tickers with 1s delay each should complete in ~1-2s, not 5-10s."""
        def slow_news(ticker, max_items=30):
            time.sleep(1.0)  # Simulate network latency
            return _mock_news_scraper(ticker, max_items)

        def slow_reddit(ticker, max_items=30):
            time.sleep(1.0)
            return _mock_reddit_scraper(ticker, max_items)

        mock_news.fetch_news = slow_news
        mock_reddit.fetch_posts = slow_reddit

        start = time.time()
        response = client.post("/api/sentiment/full-pipeline", json={
            "tickers": ["AAPL", "MSFT", "GOOG", "AMZN", "META"],
            "sources": ["news", "reddit"],
            "max_items_per_source": 3,
        })
        elapsed = time.time() - start

        assert response.status_code == 200
        # 5 tickers × 2 sources × 1s each = 10s sequential
        # With 10 parallel workers, should be ~1-2s (wall time of single ticker)
        assert elapsed < 5.0, f"Parallel collection took {elapsed:.1f}s, expected <5s"


class TestCollectEndpoint:
    """Tests for /api/sentiment/collect endpoint."""

    @patch("routers.sentiment.news_scraper")
    def test_collect_returns_texts(self, mock_news):
        """Collect endpoint returns texts grouped by ticker."""
        mock_news.fetch_news = _mock_news_scraper

        response = client.post("/api/sentiment/collect", json={
            "tickers": ["AAPL", "MSFT"],
            "sources": ["news"],
            "max_items_per_source": 5,
        })

        assert response.status_code == 200
        data = response.json()
        assert "AAPL" in data["data"]
        assert "MSFT" in data["data"]
        assert data["total_collected"] > 0
