"""News headline scraper using Finnhub API and Google News RSS."""

import requests
import feedparser
import logging
from datetime import datetime, timedelta, date
from typing import Optional

from models.sentiment import SentimentText, SentimentSource
from config import get_settings

logger = logging.getLogger(__name__)


class NewsScraper:
    """Fetches financial news headlines from multiple sources."""

    def __init__(self):
        self.settings = get_settings()

    def fetch_news(self, ticker: str, max_items: int = 30) -> list[SentimentText]:
        """Fetch news headlines for a ticker from all available sources."""
        results: list[SentimentText] = []

        # Finnhub
        finnhub_news = self._fetch_finnhub(ticker, max_items // 2)
        results.extend(finnhub_news)

        # Google News RSS
        rss_news = self._fetch_google_news_rss(ticker, max_items // 2)
        results.extend(rss_news)

        # De-duplicate by headline text
        seen = set()
        unique_results = []
        for item in results:
            normalized = item.text.strip().lower()
            if normalized not in seen:
                seen.add(normalized)
                unique_results.append(item)

        return unique_results[:max_items]

    def _fetch_finnhub(self, ticker: str, max_items: int) -> list[SentimentText]:
        """Fetch company news from Finnhub API."""
        if not self.settings.finnhub_api_key:
            logger.debug("Finnhub API key not configured, skipping")
            return []

        try:
            today = date.today()
            from_date = today - timedelta(days=7)

            url = "https://finnhub.io/api/v1/company-news"
            params = {
                "symbol": ticker,
                "from": from_date.isoformat(),
                "to": today.isoformat(),
                "token": self.settings.finnhub_api_key,
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            articles = response.json()

            results = []
            for article in articles[:max_items]:
                headline = article.get("headline", "").strip()
                if not headline:
                    continue

                pub_date = None
                if "datetime" in article:
                    try:
                        pub_date = datetime.fromtimestamp(article["datetime"]).date()
                    except (ValueError, OSError):
                        pass

                results.append(SentimentText(
                    source=SentimentSource.NEWS,
                    text=headline,
                    url=article.get("url"),
                    published_date=pub_date,
                ))

            logger.info(f"Fetched {len(results)} Finnhub articles for {ticker}")
            return results

        except Exception as e:
            logger.error(f"Finnhub error for {ticker}: {e}")
            return []

    def _fetch_google_news_rss(self, ticker: str, max_items: int) -> list[SentimentText]:
        """Fetch news from Google News RSS feed."""
        try:
            query = f"{ticker}+stock"
            url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

            feed = feedparser.parse(url)
            results = []

            for entry in feed.entries[:max_items]:
                title = entry.get("title", "").strip()
                if not title:
                    continue

                pub_date = None
                if "published_parsed" in entry and entry.published_parsed:
                    try:
                        pub_date = date(*entry.published_parsed[:3])
                    except (ValueError, TypeError):
                        pass

                results.append(SentimentText(
                    source=SentimentSource.NEWS,
                    text=title,
                    url=entry.get("link"),
                    published_date=pub_date,
                ))

            logger.info(f"Fetched {len(results)} Google News articles for {ticker}")
            return results

        except Exception as e:
            logger.error(f"Google News RSS error for {ticker}: {e}")
            return []
