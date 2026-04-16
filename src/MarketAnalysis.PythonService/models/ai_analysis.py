"""Pydantic models for AI analysis structured outputs."""

from pydantic import BaseModel, Field, model_validator
from typing import Optional


class SentimentAnalysisResponse(BaseModel):
    """Structured sentiment response from Ollama."""
    positive: float = Field(..., ge=0.0, le=1.0)
    negative: float = Field(..., ge=0.0, le=1.0)
    neutral: float = Field(..., ge=0.0, le=1.0)
    label: str = Field(..., pattern="^(positive|negative|neutral)$")


class TradeLevelResponse(BaseModel):
    """LLM-suggested trade levels with rationale."""
    entry: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    profit_target: float = Field(..., gt=0)
    exit_price: float = Field(..., gt=0)
    rationale: str

    @model_validator(mode='after')
    def validate_levels(self):
        if not (self.stop_loss < self.entry < self.profit_target):
            raise ValueError(f"Invalid trade levels: stop_loss ({self.stop_loss}) must be < entry ({self.entry}) < profit_target ({self.profit_target})")
        return self


class AnalystReportResponse(BaseModel):
    """Full AI analyst report with outlook and trade levels."""
    summary: str
    outlook: str
    key_factors: list[str]
    risk_factors: list[str]
    recommendation: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    trade_levels: TradeLevelResponse
