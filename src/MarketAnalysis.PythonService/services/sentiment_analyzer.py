"""FinBERT-based financial sentiment analyzer."""

import logging
from typing import Optional
import threading

from models.sentiment import SentimentResult

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """Singleton FinBERT sentiment analysis engine with GPU acceleration."""

    _instance: Optional["SentimentAnalyzer"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._pipeline = None
        self._device_name = "cpu"
        self._batch_size = 32
        self._load_model()

    def _load_model(self):
        """Load FinBERT model on GPU (device=0) when CUDA is available, CPU otherwise."""
        try:
            import torch
            from transformers import pipeline as hf_pipeline

            # GPU provides 10-60x FinBERT speedup; auto-detect and fall back to CPU
            if torch.cuda.is_available():
                device = 0  # First CUDA device
                self._device_name = "cuda"
                # GPU VRAM (16GB on A4000) handles 64-text batches with FinBERT (~440MB model)
                self._batch_size = 64
                logger.info(f"CUDA GPU detected: {torch.cuda.get_device_name(0)}")
            else:
                device = -1  # CPU
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
            logger.info(f"FinBERT model loaded on {self._device_name} (batch_size={self._batch_size})")

        except Exception as e:
            logger.error(f"Failed to load FinBERT model: {e}")
            logger.warning("Sentiment analysis will use fallback scoring")
            self._pipeline = None

    @property
    def device(self) -> str:
        """Returns 'cuda' or 'cpu' indicating active compute device."""
        return self._device_name

    @property
    def batch_size(self) -> int:
        """Batch size tuned per device: 64 for GPU, 32 for CPU."""
        return self._batch_size

    @classmethod
    def get_instance(cls) -> "SentimentAnalyzer":
        """Get or create the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def analyze_texts(self, texts: list[str], batch_size: int | None = None) -> list[SentimentResult]:
        """
        Analyze a batch of texts using FinBERT.

        Returns SentimentResult per text with positive/negative/neutral scores.
        Uses device-tuned batch size (64 GPU, 32 CPU) unless overridden.
        """
        if not texts:
            return []

        if self._pipeline is None:
            return self._fallback_analyze(texts)

        effective_batch_size = batch_size if batch_size is not None else self._batch_size
        results: list[SentimentResult] = []

        try:
            # Process in batches sized for the active device
            for i in range(0, len(texts), effective_batch_size):
                batch = texts[i : i + effective_batch_size]

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
