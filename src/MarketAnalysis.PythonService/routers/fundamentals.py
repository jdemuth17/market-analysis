"""Fundamentals scoring API endpoints."""

from fastapi import APIRouter, HTTPException
import logging

from models.fundamentals import (
    FundamentalScoreRequest, FundamentalScoreResponse,
    BatchFundamentalScoreRequest, BatchFundamentalScoreResponse,
)
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


@router.post("/score-batch", response_model=BatchFundamentalScoreResponse)
async def score_fundamentals_batch(request: BatchFundamentalScoreRequest):
    """Score multiple stocks' fundamentals in a single call."""
    scores = []
    for item in request.items:
        try:
            scores.append(FundamentalAnalyzer.score(item))
        except Exception as e:
            logger.error(f"Batch fundamental scoring error for {item.ticker}: {e}")
            scores.append(FundamentalScoreResponse(
                ticker=item.ticker,
                value_score=50, quality_score=50, growth_score=50,
                safety_score=50, composite_score=50,
                error=str(e),
            ))
    return BatchFundamentalScoreResponse(scores=scores)
