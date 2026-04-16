"""FinBERT-based financial sentiment analyzer."""

import logging
from typing import Optional
import threading

from models.sentiment import SentimentResult
from models.ai_analysis import SentimentAnalysisResponse
from config import get_settings
from services.ollama_client import OllamaClient, OllamaQueueFullError
import json

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """Singleton FinBERT sentiment analysis engine with GPU acceleration and VADER fallback."""

    _instance: Optional["SentimentAnalyzer"] = None
    _lock = threading.Lock()

    def __init__(self, ollama: OllamaClient = None):
        self._pipeline = None
        self._ollama = ollama
        self._vader = None
        self._device_name = "cpu"
        self._batch_size = 32
        if self._ollama is None:
            self._load_model()

    def _load_model(self):
        """Initialize Ollama client for sentiment analysis."""
        try:
            settings = get_settings()
            if settings.ollama_api_key and len(settings.ollama_api_key) >= 10:
                self._ollama = OllamaClient(settings)
                logger.info("Ollama client initialized for sentiment analysis")
            else:
                logger.warning("MA_OLLAMA_API_KEY not set or too short, using VADER-only mode")
        except Exception as e:
            logger.error(f"Failed to initialize Ollama client: {e}")
            logger.warning("Ollama unavailable, using VADER fallback")
            self._ollama = None

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

    async def analyze_texts(self, texts: list[str], batch_size: int | None = None, use_vader: bool = False) -> list[SentimentResult]:
        """
        Analyze a batch of texts using Ollama Cloud or VADER.

        Args:
            texts: List of strings to analyze
            batch_size: Override default batch size
            use_vader: If True, uses the lightweight VADER analyzer instead of Ollama.
        """
        if not texts:
            return []

        if use_vader:
            return self._analyze_vader(texts)

        if self._ollama is None:
            return self._analyze_vader(texts)

        effective_batch_size = batch_size if batch_size is not None else self._batch_size
        results: list[SentimentResult] = []
        settings = get_settings()

        try:
            for i in range(0, len(texts), effective_batch_size):
                batch = texts[i : i + effective_batch_size]
                cleaned = [t.strip()[:512] for t in batch if t.strip()]
                if not cleaned: continue

                for text in cleaned:
                    try:
                        messages = [
                            {"role": "system", "content": "You are a financial sentiment classifier. Analyze the following text and return sentiment scores."},
                            {"role": "user", "content": text}
                        ]
                        
                        response = await self._ollama.chat(
                            model=settings.ollama_sentiment_model,
                            messages=messages,
                            format_schema=SentimentAnalysisResponse.model_json_schema()
                        )
                        
                        sentiment_data = response.get("message", {}).get("content", "{}")
                        parsed = json.loads(sentiment_data)
                        
                        results.append(SentimentResult(
                            text=text[:200],
                            positive=round(parsed["positive"], 4),
                            negative=round(parsed["negative"], 4),
                            neutral=round(parsed["neutral"], 4),
                            label=parsed["label"],
                        ))
                    except OllamaQueueFullError:
                        logger.warning(f"Ollama queue full for text, using VADER fallback")
                        vader_result = self._analyze_vader([text])[0]
                        results.append(vader_result)
                    except Exception as e:
                        logger.warning(f"Ollama sentiment failed for text, using VADER: {e}")
                        vader_result = self._analyze_vader([text])[0]
                        results.append(vader_result)

        except Exception as e:
            logger.error(f"Ollama batch inference error: {e}")
            results.extend(self._analyze_vader(texts[len(results):]))

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
