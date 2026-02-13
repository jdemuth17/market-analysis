from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import os

# Clear SSL certificate overrides that break yfinance on corporate networks
for var in ("CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE"):
    os.environ.pop(var, None)

from routers import market_data, technicals, fundamentals, sentiment, scanner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting Market Analysis Python Service...")
    # Pre-load FinBERT model on startup
    from services.sentiment_analyzer import SentimentAnalyzer
    analyzer = SentimentAnalyzer.get_instance()
    logger.info("FinBERT model loaded successfully.")
    yield
    logger.info("Shutting down Market Analysis Python Service...")


app = FastAPI(
    title="Market Analysis Python Service",
    description="Financial data fetching, technical analysis, and sentiment analysis API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market_data.router, prefix="/api/market-data", tags=["Market Data"])
app.include_router(technicals.router, prefix="/api/technicals", tags=["Technical Analysis"])
app.include_router(fundamentals.router, prefix="/api/fundamentals", tags=["Fundamentals"])
app.include_router(sentiment.router, prefix="/api/sentiment", tags=["Sentiment Analysis"])
app.include_router(scanner.router, prefix="/api/scanner", tags=["Scanner"])


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "MarketAnalysis.PythonService"}
