import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connection import get_session
from app.db.queries import get_stock_count
from app.models.model_registry import model_registry

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health_check(session: AsyncSession = Depends(get_session)):
    """Service health check with model and database status."""
    try:
        stock_count = await get_stock_count(session)
        db_status = "connected"
    except Exception as e:
        stock_count = 0
        db_status = f"error: {e}"

    model_status = model_registry.get_status()

    return {
        "status": "healthy",
        "service": "MarketAnalysis.MLService",
        "timestamp": datetime.utcnow().isoformat(),
        "database": {
            "status": db_status,
            "active_stocks": stock_count,
        },
        "models": model_status,
        "models_ready": model_registry.has_models(),
    }
