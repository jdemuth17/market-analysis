"""Sentiment analysis API endpoints."""

from fastapi import APIRouter, HTTPException
import logging
import asyncio

from models.sentiment import (
    CollectSentimentRequest, CollectSentimentResponse,
    AnalyzeSentimentRequest, AnalyzeSentimentResponse,
    FullSentimentRequest, FullSentimentResponse,
    SentimentSource, SentimentText, TickerSentiment,
)
from services.sentiment_analyzer import SentimentAnalyzer
from services.news_scraper import NewsScraper
from services.reddit_scraper import RedditScraper
from services.stocktwits_scraper import StockTwitsScraper

router = APIRouter()
logger = logging.getLogger(__name__)

news_scraper = NewsScraper()
reddit_scraper = RedditScraper()
stocktwits_scraper = StockTwitsScraper()


def _collect_texts_for_ticker(
    ticker: str,
    sources: list[SentimentSource],
    max_items_per_source: int,
) -> list[SentimentText]:
    """Collect sentiment texts from all requested sources for a ticker."""
    texts: list[SentimentText] = []

    for source in sources:
        try:
            if source == SentimentSource.NEWS:
                texts.extend(news_scraper.fetch_news(ticker, max_items_per_source))
            elif source == SentimentSource.REDDIT:
                texts.extend(reddit_scraper.fetch_posts(ticker, max_items_per_source))
            elif source == SentimentSource.STOCKTWITS:
                texts.extend(stocktwits_scraper.fetch_messages(ticker, max_items_per_source))
        except Exception as e:
            logger.error(f"Error collecting {source} for {ticker}: {e}")

    return texts


@router.post("/collect", response_model=CollectSentimentResponse)
async def collect_sentiment_texts(request: CollectSentimentRequest):
    """Collect raw text data from sentiment sources (no analysis)."""
    data: dict[str, list[SentimentText]] = {}
    total = 0

    for ticker in request.tickers:
        texts = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda t=ticker: _collect_texts_for_ticker(t, request.sources, request.max_items_per_source),
        )
        data[ticker] = texts
        total += len(texts)

    return CollectSentimentResponse(data=data, total_collected=total)


@router.post("/analyze", response_model=AnalyzeSentimentResponse)
async def analyze_texts(request: AnalyzeSentimentRequest):
    """Run FinBERT sentiment analysis on provided texts."""
    analyzer = SentimentAnalyzer.get_instance()

    results = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: analyzer.analyze_texts(request.texts),
    )

    return AnalyzeSentimentResponse(results=results)


@router.post("/full-pipeline", response_model=FullSentimentResponse)
async def full_sentiment_pipeline(request: FullSentimentRequest):
    """Collect texts from sources + run FinBERT analysis. Full pipeline."""
    analyzer = SentimentAnalyzer.get_instance()
    all_ticker_sentiments: list[TickerSentiment] = []
    total_texts = 0

    for ticker in request.tickers:
        # Collect texts
        texts = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda t=ticker: _collect_texts_for_ticker(t, request.sources, request.max_items_per_source),
        )

        # Group texts by source
        source_groups: dict[SentimentSource, list[str]] = {}
        source_headlines: dict[SentimentSource, list[str]] = {}

        for text_item in texts:
            if text_item.source not in source_groups:
                source_groups[text_item.source] = []
                source_headlines[text_item.source] = []
            source_groups[text_item.source].append(text_item.text)
            source_headlines[text_item.source].append(text_item.text[:100])

        # Analyze each source group
        for source, text_list in source_groups.items():
            if not text_list:
                continue

            results = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda tl=text_list: analyzer.analyze_texts(tl),
            )
            total_texts += len(results)

            # Aggregate scores
            if results:
                avg_pos = sum(r.positive for r in results) / len(results)
                avg_neg = sum(r.negative for r in results) / len(results)
                avg_neu = sum(r.neutral for r in results) / len(results)
            else:
                avg_pos, avg_neg, avg_neu = 0.33, 0.33, 0.34

            all_ticker_sentiments.append(TickerSentiment(
                ticker=ticker,
                source=source,
                positive_score=round(avg_pos, 4),
                negative_score=round(avg_neg, 4),
                neutral_score=round(avg_neu, 4),
                sample_size=len(results),
                individual_results=results,
                headlines=source_headlines.get(source, []),
            ))

    return FullSentimentResponse(
        data=all_ticker_sentiments,
        total_tickers=len(request.tickers),
        total_texts_analyzed=total_texts,
    )
