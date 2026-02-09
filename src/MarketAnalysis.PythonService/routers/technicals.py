"""Technical analysis API endpoints."""

from fastapi import APIRouter, HTTPException
import pandas as pd
import logging

from models.technicals import (
    IndicatorsRequest, IndicatorsResponse,
    PatternDetectionRequest, PatternDetectionResponse,
    FullTechnicalRequest, FullTechnicalResponse,
)
from services.indicator_engine import IndicatorEngine
from services.pattern_detector import PatternDetector

router = APIRouter()
logger = logging.getLogger(__name__)


def _bars_to_dataframe(bars: list[dict]) -> pd.DataFrame:
    """Convert list of bar dicts to DataFrame."""
    df = pd.DataFrame(bars)
    expected_cols = {"date", "open", "high", "low", "close", "volume"}
    # Normalize column names
    df.columns = [c.lower() for c in df.columns]
    missing = expected_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    return df


@router.post("/indicators", response_model=IndicatorsResponse)
async def compute_indicators(request: IndicatorsRequest):
    """Compute technical indicators for given OHLCV data."""
    try:
        df = _bars_to_dataframe(request.bars)
        indicators = IndicatorEngine.compute_indicators(df, request.indicators)
        return IndicatorsResponse(ticker=request.ticker, indicators=indicators)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Indicator computation error: {e}")
        return IndicatorsResponse(ticker=request.ticker, indicators=[], error=str(e))


@router.post("/patterns", response_model=PatternDetectionResponse)
async def detect_patterns(request: PatternDetectionRequest):
    """Detect chart patterns in OHLCV data."""
    try:
        df = _bars_to_dataframe(request.bars)
        detector = PatternDetector(df, lookback_days=request.lookback_days)
        patterns = detector.detect_patterns(request.patterns)
        return PatternDetectionResponse(
            ticker=request.ticker,
            detected_patterns=patterns,
            patterns_scanned=len(request.patterns),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Pattern detection error: {e}")
        return PatternDetectionResponse(
            ticker=request.ticker, detected_patterns=[], patterns_scanned=0, error=str(e),
        )


@router.post("/full-analysis", response_model=FullTechnicalResponse)
async def full_technical_analysis(request: FullTechnicalRequest):
    """Run both indicators and pattern detection in one call."""
    try:
        df = _bars_to_dataframe(request.bars)

        indicators = IndicatorEngine.compute_indicators(df, request.indicators)

        detector = PatternDetector(df, lookback_days=request.lookback_days)
        patterns = detector.detect_patterns(request.patterns)

        return FullTechnicalResponse(
            ticker=request.ticker,
            indicators=indicators,
            detected_patterns=patterns,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Full technical analysis error: {e}")
        return FullTechnicalResponse(
            ticker=request.ticker, indicators=[], detected_patterns=[], error=str(e),
        )
