from pydantic import BaseModel
from typing import Optional


class FundamentalScoreRequest(BaseModel):
    ticker: str
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    profit_margin: Optional[float] = None
    return_on_equity: Optional[float] = None
    free_cash_flow: Optional[float] = None
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    current_price: Optional[float] = None
    target_mean_price: Optional[float] = None


class FundamentalScoreResponse(BaseModel):
    ticker: str
    value_score: float  # 0-100, how undervalued
    quality_score: float  # 0-100, profitability & efficiency
    growth_score: float  # 0-100, growth metrics
    safety_score: float  # 0-100, debt & risk
    composite_score: float  # 0-100, weighted overall
    details: dict = {}
    error: Optional[str] = None
