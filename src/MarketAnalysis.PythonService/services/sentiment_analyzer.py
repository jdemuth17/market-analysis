"""FinBERT-based financial sentiment analyzer."""

import logging
from typing import Optional
import threading

from models.sentiment import SentimentResult

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """Singleton FinBERT sentiment analysis engine."""

    _instance: Optional["SentimentAnalyzer"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._pipeline = None
        self._load_model()

    def _load_model(self):
        """Load the FinBERT model."""
        try:
            from transformers import pipeline as hf_pipeline

            logger.info("Loading FinBERT model (this may take a moment on first run)...")
            self._pipeline = hf_pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                tokenizer="ProsusAI/finbert",
                truncation=True,
                max_length=512,
            )
            logger.info("FinBERT model loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load FinBERT model: {e}")
            logger.warning("Sentiment analysis will use fallback scoring")
            self._pipeline = None

    @classmethod
    def get_instance(cls) -> "SentimentAnalyzer":
        """Get or create the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def analyze_texts(self, texts: list[str], batch_size: int = 32) -> list[SentimentResult]:
        """
        Analyze a batch of texts using FinBERT.

        Returns SentimentResult per text with positive/negative/neutral scores.
        """
        if not texts:
            return []

        if self._pipeline is None:
            return self._fallback_analyze(texts)

        results: list[SentimentResult] = []

        try:
            # Process in batches
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]

                # Clean texts
                cleaned = [t.strip()[:512] for t in batch if t.strip()]
                if not cleaned:
                    continue

                # Run FinBERT inference
                raw_results = self._pipeline(cleaned)

                for text, raw in zip(cleaned, raw_results):
                    label = raw["label"].lower()
                    score = raw["score"]

                    # Map to three-way scores
                    positive = score if label == "positive" else (1 - score) / 2
                    negative = score if label == "negative" else (1 - score) / 2
                    neutral = score if label == "neutral" else (1 - score) / 2

                    # Normalize so they sum to 1
                    total = positive + negative + neutral
                    if total > 0:
                        positive /= total
                        negative /= total
                        neutral /= total

                    results.append(SentimentResult(
                        text=text[:200],
                        positive=round(positive, 4),
                        negative=round(negative, 4),
                        neutral=round(neutral, 4),
                        label=label,
                    ))

        except Exception as e:
            logger.error(f"FinBERT inference error: {e}")
            results.extend(self._fallback_analyze(texts[len(results):]))

        return results

    def _fallback_analyze(self, texts: list[str]) -> list[SentimentResult]:
        """Simple keyword-based fallback when FinBERT is unavailable."""
        positive_words = {"up", "gain", "bull", "buy", "profit", "surge", "rally", "beat", "strong", "growth", "record", "high"}
        negative_words = {"down", "loss", "bear", "sell", "crash", "drop", "fall", "miss", "weak", "decline", "low", "risk"}

        results = []
        for text in texts:
            words = set(text.lower().split())
            pos_count = len(words & positive_words)
            neg_count = len(words & negative_words)
            total = pos_count + neg_count

            if total == 0:
                pos, neg, neu = 0.1, 0.1, 0.8
            else:
                pos = pos_count / total * 0.7
                neg = neg_count / total * 0.7
                neu = 0.3

            # Normalize
            s = pos + neg + neu
            pos, neg, neu = pos / s, neg / s, neu / s

            label = "positive" if pos > neg and pos > neu else ("negative" if neg > pos and neg > neu else "neutral")

            results.append(SentimentResult(
                text=text[:200],
                positive=round(pos, 4),
                negative=round(neg, 4),
                neutral=round(neu, 4),
                label=label,
            ))

        return results
