from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    # General
    app_name: str = "MarketAnalysis Python Service"
    debug: bool = False

    # Yahoo Finance
    yahoo_max_requests_per_hour: int = 2000
    yahoo_request_delay_seconds: float = 0.5
    yahoo_bulk_chunk_size: int = 50

    # Finnhub
    finnhub_api_key: str = ""

    # Reddit (PRAW)
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "MarketAnalysis/1.0"

    # StockTwits
    stocktwits_max_requests_per_hour: int = 200

    # FinBERT
    finbert_model_name: str = "ProsusAI/finbert"
    finbert_batch_size: int = 32
    finbert_gpu_batch_size: int = 64
    finbert_max_length: int = 512

    # Ticker list cache
    ticker_list_cache_hours: int = 168  # 1 week

    model_config = {"env_file": ".env", "env_prefix": "MA_"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
