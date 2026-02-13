import logging
import os
import platform
import asyncio
from contextlib import asynccontextmanager

# Fix SSL issues with yfinance on Windows when CURL_CA_BUNDLE is set incorrectly
os.environ.pop("CURL_CA_BUNDLE", None)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.connection import engine
from app.routers import health, predict, train, backfill, models, monitor

# Fix asyncpg + Python 3.13 on Windows (ProactorEventLoop incompatible)
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MarketAnalysis.MLService starting up")
    logger.info(f"Database: {settings.database_url.split('@')[1] if '@' in settings.database_url else 'configured'}")
    logger.info(f"Model directory: {settings.model_dir}")

    # Load trained models if they exist
    from app.models.model_registry import model_registry
    await model_registry.load_all()

    yield

    logger.info("MarketAnalysis.MLService shutting down")
    await engine.dispose()


app = FastAPI(
    title="MarketAnalysis ML Service",
    description="XGBoost + LSTM ensemble scoring for stock analysis",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/ml", tags=["Health"])
app.include_router(predict.router, prefix="/api/ml", tags=["Prediction"])
app.include_router(train.router, prefix="/api/ml", tags=["Training"])
app.include_router(backfill.router, prefix="/api/ml", tags=["Backfill"])
app.include_router(models.router, prefix="/api/ml", tags=["Models"])
app.include_router(monitor.router, prefix="/api/ml", tags=["Monitoring"])
