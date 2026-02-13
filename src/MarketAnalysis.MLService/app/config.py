from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_prefix": "ML_"}

    # Database (same PostgreSQL as Market Analysis)
    database_url: str = "postgresql+asyncpg://market:dev_password@127.0.0.1:5433/market_analysis?ssl=disable"

    # Existing Python service (for backfill calls)
    python_service_url: str = "http://localhost:8000"

    # Model paths
    model_dir: str = "trained_models"

    # Training defaults
    xgboost_n_estimators: int = 500
    xgboost_max_depth: int = 6
    xgboost_learning_rate: float = 0.05

    lstm_hidden_size_1: int = 128
    lstm_hidden_size_2: int = 64
    lstm_dropout: float = 0.3
    lstm_sequence_length: int = 60
    lstm_batch_size: int = 256
    lstm_epochs: int = 50
    lstm_patience: int = 10
    lstm_learning_rate: float = 0.001

    # Feature config
    num_features: int = 45

    # Backfill
    backfill_price_period: str = "3y"
    backfill_batch_size: int = 50
    backfill_technical_lookback: int = 120

    # Scoring
    min_composite_score: float = 30.0
    top_n_per_category: int = 50

    # Server
    debug: bool = False


settings = Settings()
