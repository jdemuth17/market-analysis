"""AI analysis endpoints: analyst reports and trade levels."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from models.ai_analysis import AnalystReportResponse, TradeLevelResponse
from services.ai_report_generator import AiReportGenerator
from services.ollama_client import OllamaClient
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class AiAnalysisRequest(BaseModel):
    ticker: str
    price_history: list[dict]
    technicals: dict
    fundamentals: dict
    sentiment: dict


class BatchAiAnalysisRequest(BaseModel):
    items: list[AiAnalysisRequest]


def get_ollama_client() -> OllamaClient:
    """Dependency to get singleton OllamaClient from app.state."""
    from main import app
    return app.state.ollama_client


@router.post("/report")
async def generate_report(request: AiAnalysisRequest, ollama: OllamaClient = Depends(get_ollama_client)) -> AnalystReportResponse:
    """Generate AI analyst report for a ticker."""
    try:
        generator = AiReportGenerator(ollama)
        report = await generator.generate_report(request)
        return report
    except Exception as e:
        logger.error(f"Failed to generate AI report for {request.ticker}: {e}")
        return {
            "error": type(e).__name__,
            "message": str(e),
            "ticker": request.ticker
        }


@router.post("/trade-levels")
async def generate_trade_levels(request: AiAnalysisRequest, ollama: OllamaClient = Depends(get_ollama_client)) -> TradeLevelResponse:
    """Generate LLM-suggested trade levels for a ticker."""
    try:
        generator = AiReportGenerator(ollama)
        report = await generator.generate_report(request)
        return report.trade_levels
    except Exception as e:
        logger.error(f"Failed to generate trade levels for {request.ticker}: {e}")
        return {
            "error": type(e).__name__,
            "message": str(e),
            "ticker": request.ticker
        }


@router.post("/batch-reports")
async def generate_batch_reports(request: BatchAiAnalysisRequest, ollama: OllamaClient = Depends(get_ollama_client)) -> list:
    """Generate AI reports for multiple tickers."""
    from config import get_settings
    settings = get_settings()
    
    if len(request.items) > settings.ai_batch_max:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size {len(request.items)} exceeds maximum {settings.ai_batch_max}"
        )
    
    generator = AiReportGenerator(ollama)
    results = []
    
    for item in request.items:
        try:
            report = await generator.generate_report(item)
            results.append({
                "ticker": item.ticker,
                "success": True,
                "data": report.model_dump()
            })
        except Exception as e:
            logger.error(f"Failed to generate report for {item.ticker} in batch: {e}")
            results.append({
                "ticker": item.ticker,
                "success": False,
                "error": type(e).__name__,
                "message": str(e)
            })
    
    return results
