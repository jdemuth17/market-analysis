"""Sentiment analysis API endpoints.

Two-phase pipeline: parallel I/O-bound text collection via ThreadPoolExecutor,
then single batched FinBERT GPU inference for optimal throughput.
"""

from fastapi import APIRouter, HTTPException
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed

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

# Scrapers are I/O-bound (HTTP/PRAW calls ~3-12s each); GIL not a bottleneck
_collection_pool = ThreadPoolExecutor(max_workers=10)


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


def _collect_all_tickers_parallel(
    tickers: list[str],
    sources: list[SentimentSource],
    max_items_per_source: int,
) -> dict[str, list[SentimentText]]:
    """Collect texts for all tickers concurrently via thread pool.

    Returns {ticker: [SentimentText, ...]} with partial results on per-ticker errors.
    """
    results: dict[str, list[SentimentText]] = {}
    futures = {
        _collection_pool.submit(
            _collect_texts_for_ticker, ticker, sources, max_items_per_source
        ): ticker
        for ticker in tickers
    }

    for future in as_completed(futures):
        ticker = futures[future]
        try:
            results[ticker] = future.result()
        except Exception as e:
            logger.error(f"Collection failed for {ticker}: {e}")
            results[ticker] = []

    return results


@router.post("/collect", response_model=CollectSentimentResponse)
async def collect_sentiment_texts(request: CollectSentimentRequest):
    """Collect raw text data from sentiment sources (no analysis)."""
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None,
        lambda: _collect_all_tickers_parallel(
            request.tickers, request.sources, request.max_items_per_source
        ),
    )
    total = sum(len(texts) for texts in data.values())
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
    """Two-phase pipeline: parallel text collection, then single batched GPU inference.

    Phase 1 collects texts from all tickers concurrently (I/O-bound scrapers).
    Phase 2 runs one FinBERT inference pass over all collected texts (GPU-optimized).
    Results are regrouped by (ticker, source) for the response.
    """
    analyzer = SentimentAnalyzer.get_instance()
    loop = asyncio.get_event_loop()

    # --- Phase 1: Parallel text collection across all tickers ---
    logger.info(f"Phase 1: Collecting texts for {len(request.tickers)} tickers in parallel")
    ticker_texts = await loop.run_in_executor(
        None,
        lambda: _collect_all_tickers_parallel(
            request.tickers, request.sources, request.max_items_per_source
        ),
    )

    # Build flat list with index tracking for regrouping after inference
    # Each entry: (ticker, source, text_string, headline)
    indexed_items: list[tuple[str, SentimentSource, str, str]] = []
    for ticker, texts in ticker_texts.items():
        for text_item in texts:
            indexed_items.append((ticker, text_item.source, text_item.text, text_item.text[:100]))

    if not indexed_items:
        return FullSentimentResponse(
            data=[], total_tickers=len(request.tickers), total_texts_analyzed=0
        )

    # --- Phase 2: Single batched FinBERT inference over all texts ---
    all_text_strings = [item[2] for item in indexed_items]
    logger.info(
        f"Phase 2: Running FinBERT on {len(all_text_strings)} texts "
        f"(device={analyzer.device}, batch_size={analyzer.batch_size})"
    )
    all_results = await loop.run_in_executor(
        None,
        lambda: analyzer.analyze_texts(all_text_strings),
    )

    # --- Regroup results by (ticker, source) ---
    from collections import defaultdict

    group_results: dict[tuple[str, SentimentSource], list] = defaultdict(list)
    group_headlines: dict[tuple[str, SentimentSource], list[str]] = defaultdict(list)

    for (ticker, source, _text, headline), result in zip(indexed_items, all_results):
        key = (ticker, source)
        group_results[key].append(result)
        group_headlines[key].append(headline)

    all_ticker_sentiments: list[TickerSentiment] = []
    total_texts = len(all_results)

    for (ticker, source), results in group_results.items():
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
            headlines=group_headlines.get((ticker, source), []),
        ))

    return FullSentimentResponse(
        data=all_ticker_sentiments,
        total_tickers=len(request.tickers),
        total_texts_analyzed=total_texts,
    )
