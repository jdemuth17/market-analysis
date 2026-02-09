"""StockTwits scraper for stock sentiment data."""

import requests
import logging
from datetime import datetime, date
from typing import Optional

from models.sentiment import SentimentText, SentimentSource
from utils.rate_limiter import stocktwits_rate_limiter

logger = logging.getLogger(__name__)


class StockTwitsScraper:
    """Fetches messages from StockTwits public API."""

    BASE_URL = "https://api.stocktwits.com/api/2"

    def fetch_messages(self, ticker: str, max_items: int = 30) -> list[SentimentText]:
        """Fetch recent messages for a ticker from StockTwits."""
        results: list[SentimentText] = []

        try:
            stocktwits_rate_limiter.wait()

            url = f"{self.BASE_URL}/streams/symbol/{ticker}.json"
            response = requests.get(url, timeout=10)

            if response.status_code == 404:
                logger.debug(f"StockTwits: No data for {ticker}")
                return []

            if response.status_code == 429:
                logger.warning("StockTwits rate limit hit")
                return []

            response.raise_for_status()
            data = response.json()

            messages = data.get("messages", [])

            for msg in messages[:max_items]:
                body = msg.get("body", "").strip()
                if not body or len(body) < 10:
                    continue

                pub_date = None
                created_at = msg.get("created_at")
                if created_at:
                    try:
                        pub_date = datetime.strptime(
                            created_at, "%Y-%m-%dT%H:%M:%SZ"
                        ).date()
                    except ValueError:
                        pass

                author = None
                user = msg.get("user")
                if user:
                    author = user.get("username")

                results.append(SentimentText(
                    source=SentimentSource.STOCKTWITS,
                    text=body,
                    url=f"https://stocktwits.com/symbol/{ticker}",
                    published_date=pub_date,
                    author=author,
                ))

            logger.info(f"Fetched {len(results)} StockTwits messages for {ticker}")

        except requests.exceptions.RequestException as e:
            logger.error(f"StockTwits API error for {ticker}: {e}")
        except Exception as e:
            logger.error(f"StockTwits parsing error for {ticker}: {e}")

        return results
