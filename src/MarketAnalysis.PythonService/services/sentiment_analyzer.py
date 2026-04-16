"""FinBERT-based financial sentiment analyzer."""

import logging
from typing import Optional
import threading

from models.sentiment import SentimentResult

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """Singleton FinBERT sentiment analysis engine with GPU acceleration and VADER fallback."""

    _instance: Optional["SentimentAnalyzer"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._pipeline = None
        self._vader = None
        self._device_name = "cpu"
        self._batch_size = 32
        self._load_model()

    def _load_model(self):
        """Load FinBERT model on GPU (device=0) when CUDA is available, CPU otherwise."""
        try:
            import torch
            from transformers import pipeline as hf_pipeline

            # Skip deep learning model if memory is extremely tight
            # This can be set via env var if needed, but here we just try to load
            if torch.cuda.is_available():
                device = 0
                self._device_name = "cuda"
                self._batch_size = 64
                logger.info(f"CUDA GPU detected: {torch.cuda.get_device_name(0)}")
            else:
                device = -1
                self._device_name = "cpu"
                self._batch_size = 32
                logger.info("No CUDA GPU detected, using CPU")

            logger.info("Loading FinBERT model...")
            self._pipeline = hf_pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                tokenizer="ProsusAI/finbert",
                truncation=True,
                max_length=512,
                device=device,
            )
            logger.info(f"FinBERT model loaded on {self._device_name}")

        except Exception as e:
            logger.error(f"Failed to load FinBERT model: {e}")
            logger.warning("FinBERT unavailable, using fallback/VADER only")
            self._pipeline = None

    def _get_vader(self):
        """Lazy load VADER analyzer."""
        if self._vader is None:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            self._vader = SentimentIntensityAnalyzer()
        return self._vader

    @property
    def device(self) -> str:
        return self._device_name

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @classmethod
    def get_instance(cls) -> "SentimentAnalyzer":
        """Get or create the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def analyze_texts(self, texts: list[str], batch_size: int | None = None, use_vader: bool = False) -> list[SentimentResult]:
        """
        Analyze a batch of texts using FinBERT or VADER.

        Args:
            texts: List of strings to analyze
            batch_size: Override default batch size for FinBERT
            use_vader: If True, uses the lightweight VADER analyzer instead of FinBERT.
        """
        if not texts:
            return []

        if use_vader:
            return self._analyze_vader(texts)

        if self._pipeline is None:
            return self._fallback_analyze(texts)

        effective_batch_size = batch_size if batch_size is not None else self._batch_size
        results: list[SentimentResult] = []

        try:
            for i in range(0, len(texts), effective_batch_size):
                batch = texts[i : i + effective_batch_size]
                cleaned = [t.strip()[:512] for t in batch if t.strip()]
                if not cleaned: continue

                raw_results = self._pipeline(cleaned)

                for text, raw in zip(cleaned, raw_results):
                    label = raw["label"].lower()
                    score = raw["score"]

                    # Map to three-way scores
                    positive = score if label == "positive" else (1 - score) / 2
                    negative = score if label == "negative" else (1 - score) / 2
                    neutral = score if label == "neutral" else (1 - score) / 2

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

    def _analyze_vader(self, texts: list[str]) -> list[SentimentResult]:
        """Lightweight analysis using VADER (lexicon and rule-based)."""
        vader = self._get_vader()
        results = []
        for text in texts:
            scores = vader.polarity_scores(text)
            # VADER returns: neg, neu, pos, compound
            # We map compound to our label and use neg/neu/pos directly
            compound = scores["compound"]
            
            if compound >= 0.05: label = "positive"
            elif compound <= -0.05: label = "negative"
            else: label = "neutral"

            results.append(SentimentResult(
                text=text[:200],
                positive=round(scores["pos"], 4),
                negative=round(scores["neg"], 4),
                neutral=round(scores["neu"], 4),
                label=label,
            ))
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
