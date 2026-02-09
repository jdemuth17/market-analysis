"""Reddit scraper for stock-related sentiment data using PRAW."""

import logging
from datetime import datetime, date
from typing import Optional

from models.sentiment import SentimentText, SentimentSource
from config import get_settings

logger = logging.getLogger(__name__)


class RedditScraper:
    """Fetches stock-related posts from Reddit subreddits."""

    SUBREDDITS = ["wallstreetbets", "stocks", "investing"]

    def __init__(self):
        self.settings = get_settings()
        self._reddit = None

    def _get_reddit(self):
        """Lazy initialize PRAW Reddit client."""
        if self._reddit is None:
            if not self.settings.reddit_client_id or not self.settings.reddit_client_secret:
                logger.warning("Reddit API credentials not configured")
                return None

            try:
                import praw
                self._reddit = praw.Reddit(
                    client_id=self.settings.reddit_client_id,
                    client_secret=self.settings.reddit_client_secret,
                    user_agent=self.settings.reddit_user_agent,
                )
            except Exception as e:
                logger.error(f"Failed to initialize PRAW: {e}")
                return None

        return self._reddit

    def fetch_posts(self, ticker: str, max_items: int = 30) -> list[SentimentText]:
        """Search Reddit for posts mentioning a ticker."""
        reddit = self._get_reddit()
        if reddit is None:
            return []

        results: list[SentimentText] = []
        items_per_sub = max(max_items // len(self.SUBREDDITS), 5)

        for subreddit_name in self.SUBREDDITS:
            try:
                subreddit = reddit.subreddit(subreddit_name)

                # Search for ticker mentions (both $TICKER and plain TICKER)
                search_queries = [f"${ticker}", ticker]

                for query in search_queries:
                    try:
                        submissions = subreddit.search(
                            query,
                            sort="new",
                            time_filter="week",
                            limit=items_per_sub,
                        )

                        for submission in submissions:
                            # Skip very low-quality posts
                            if submission.score < 2:
                                continue

                            title = submission.title.strip()
                            if not title:
                                continue

                            # Use title + selftext snippet for richer context
                            text = title
                            if submission.selftext:
                                snippet = submission.selftext[:200].strip()
                                if snippet:
                                    text = f"{title}. {snippet}"

                            pub_date = None
                            try:
                                pub_date = datetime.fromtimestamp(submission.created_utc).date()
                            except (ValueError, OSError):
                                pass

                            results.append(SentimentText(
                                source=SentimentSource.REDDIT,
                                text=text,
                                url=f"https://reddit.com{submission.permalink}",
                                published_date=pub_date,
                                author=str(submission.author) if submission.author else None,
                            ))

                    except Exception as e:
                        logger.error(f"Reddit search error for '{query}' in r/{subreddit_name}: {e}")

            except Exception as e:
                logger.error(f"Reddit subreddit error for r/{subreddit_name}: {e}")

        # De-duplicate
        seen = set()
        unique = []
        for item in results:
            key = item.text.strip().lower()[:100]
            if key not in seen:
                seen.add(key)
                unique.append(item)

        logger.info(f"Fetched {len(unique)} Reddit posts for {ticker}")
        return unique[:max_items]
