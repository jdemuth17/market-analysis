from pydantic import BaseModel, Field
from datetime import date
from typing import Optional


class OHLCVBar(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int


class FetchPricesRequest(BaseModel):
    tickers: list[str]
    period: str = Field(default="6mo", description="1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max")
    interval: str = Field(default="1d", description="1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo")


class TickerPriceData(BaseModel):
    ticker: str
    bars: list[OHLCVBar]
    error: Optional[str] = None


class FetchPricesResponse(BaseModel):
    data: list[TickerPriceData]
    total_tickers: int
    successful: int
    failed: int


class FetchFundamentalsRequest(BaseModel):
    tickers: list[str]


class FundamentalData(BaseModel):
    ticker: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    exchange: Optional[str] = None
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_book: Optional[float] = None
    revenue_per_share: Optional[float] = None
    earnings_per_share: Optional[float] = None
    debt_to_equity: Optional[float] = None
    profit_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    return_on_equity: Optional[float] = None
    free_cash_flow: Optional[float] = None
    dividend_yield: Optional[float] = None
    revenue: Optional[float] = None
    market_cap: Optional[float] = None
    beta: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    current_price: Optional[float] = None
    target_mean_price: Optional[float] = None
    recommendation_key: Optional[str] = None
    raw_info: Optional[dict] = None
    error: Optional[str] = None


class FetchFundamentalsResponse(BaseModel):
    data: list[FundamentalData]
    total_tickers: int
    successful: int
    failed: int
