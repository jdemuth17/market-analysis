from pydantic import BaseModel, Field
from datetime import date
from typing import Optional
from enum import Enum


class PatternType(str, Enum):
    DOUBLE_TOP = "double_top"
    DOUBLE_BOTTOM = "double_bottom"
    HEAD_AND_SHOULDERS = "head_and_shoulders"
    INVERSE_HEAD_AND_SHOULDERS = "inverse_head_and_shoulders"
    BULL_FLAG = "bull_flag"
    BEAR_FLAG = "bear_flag"
    ASCENDING_TRIANGLE = "ascending_triangle"
    DESCENDING_TRIANGLE = "descending_triangle"
    SYMMETRICAL_TRIANGLE = "symmetrical_triangle"
    RISING_WEDGE = "rising_wedge"
    FALLING_WEDGE = "falling_wedge"
    PENNANT = "pennant"
    CUP_AND_HANDLE = "cup_and_handle"


class SignalDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class PatternStatus(str, Enum):
    FORMING = "forming"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class IndicatorType(str, Enum):
    SMA_20 = "sma_20"
    SMA_50 = "sma_50"
    SMA_200 = "sma_200"
    EMA_9 = "ema_9"
    EMA_21 = "ema_21"
    EMA_50 = "ema_50"
    RSI_14 = "rsi_14"
    MACD = "macd"
    BOLLINGER_BANDS = "bollinger_bands"
    ADX = "adx"
    STOCHASTIC = "stochastic"
    CCI = "cci"
    WILLIAMS_R = "williams_r"
    ATR = "atr"
    OBV = "obv"
    VWAP = "vwap"
    VOLUME_SMA = "volume_sma"


class IndicatorValue(BaseModel):
    name: str
    values: dict[str, Optional[float]]  # date_str -> value


class IndicatorsRequest(BaseModel):
    ticker: str
    bars: list[dict]  # OHLCV bars as dicts
    indicators: list[IndicatorType]


class IndicatorsResponse(BaseModel):
    ticker: str
    indicators: list[IndicatorValue]
    error: Optional[str] = None


class DetectedPattern(BaseModel):
    pattern_type: PatternType
    direction: SignalDirection
    confidence: float = Field(ge=0, le=100)
    start_date: date
    end_date: date
    key_levels: dict[str, float] = {}  # resistance, support, neckline, target
    status: PatternStatus = PatternStatus.FORMING
    metadata: dict = {}


class PatternDetectionRequest(BaseModel):
    ticker: str
    bars: list[dict]  # OHLCV bars as dicts
    patterns: list[PatternType]
    lookback_days: int = Field(default=120, description="Number of bars to look back for patterns")


class PatternDetectionResponse(BaseModel):
    ticker: str
    detected_patterns: list[DetectedPattern]
    patterns_scanned: int
    error: Optional[str] = None


class FullTechnicalRequest(BaseModel):
    ticker: str
    bars: list[dict]
    indicators: list[IndicatorType]
    patterns: list[PatternType]
    lookback_days: int = 120


class FullTechnicalResponse(BaseModel):
    ticker: str
    indicators: list[IndicatorValue]
    detected_patterns: list[DetectedPattern]
    error: Optional[str] = None
