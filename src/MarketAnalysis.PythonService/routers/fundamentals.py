"""Fundamentals scoring API endpoints."""

from fastapi import APIRouter, HTTPException
import logging

from models.fundamentals import FundamentalScoreRequest, FundamentalScoreResponse
from services.fundamental_analyzer import FundamentalAnalyzer

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/score", response_model=FundamentalScoreResponse)
async def score_fundamentals(request: FundamentalScoreRequest):
    """Score a stock's fundamentals across value, quality, growth, and safety dimensions."""
    try:
        result = FundamentalAnalyzer.score(request)
        return result
    except Exception as e:
        logger.error(f"Fundamental scoring error: {e}")
        return FundamentalScoreResponse(
            ticker=request.ticker,
            value_score=50, quality_score=50, growth_score=50,
            safety_score=50, composite_score=50,
            error=str(e),
        )
