from pydantic import BaseModel, Field
from datetime import date
from typing import Optional
from enum import Enum


class SentimentSource(str, Enum):
    NEWS = "news"
    REDDIT = "reddit"
    STOCKTWITS = "stocktwits"


class SentimentText(BaseModel):
    source: SentimentSource
    text: str
    url: Optional[str] = None
    published_date: Optional[date] = None
    author: Optional[str] = None


class SentimentResult(BaseModel):
    text: str
    positive: float
    negative: float
    neutral: float
    label: str  # "positive", "negative", "neutral"


class TickerSentiment(BaseModel):
    ticker: str
    source: SentimentSource
    positive_score: float
    negative_score: float
    neutral_score: float
    sample_size: int
    individual_results: list[SentimentResult] = []
    headlines: list[str] = []
    error: Optional[str] = None


class CollectSentimentRequest(BaseModel):
    tickers: list[str]
    sources: list[SentimentSource]
    max_items_per_source: int = Field(default=30, description="Max texts to collect per source per ticker")


class CollectSentimentResponse(BaseModel):
    data: dict[str, list[SentimentText]]  # ticker -> list of texts
    total_collected: int


class AnalyzeSentimentRequest(BaseModel):
    texts: list[str]


class AnalyzeSentimentResponse(BaseModel):
    results: list[SentimentResult]


class FullSentimentRequest(BaseModel):
    tickers: list[str]
    sources: list[SentimentSource]
    max_items_per_source: int = 30


class FullSentimentResponse(BaseModel):
    data: list[TickerSentiment]
    total_tickers: int
    total_texts_analyzed: int
