"""Fundamental data scoring engine."""

import logging
from typing import Optional
from models.fundamentals import FundamentalScoreRequest, FundamentalScoreResponse

logger = logging.getLogger(__name__)


class FundamentalAnalyzer:
    """Scores stocks based on fundamental data metrics."""

    @staticmethod
    def score(req: FundamentalScoreRequest) -> FundamentalScoreResponse:
        """
        Compute value, quality, growth, and safety scores from fundamental data.
        Each sub-score is 0-100. Composite is weighted average.
        """
        details = {}

        # --- Value Score (how undervalued) ---
        value_components = []

        if req.pe_ratio is not None and req.pe_ratio > 0:
            # Lower P/E is better. Score: 100 at P/E=5, 0 at P/E=50
            pe_score = max(0, min(100, (50 - req.pe_ratio) / 45 * 100))
            value_components.append(pe_score)
            details["pe_score"] = round(pe_score, 1)

        if req.forward_pe is not None and req.forward_pe > 0:
            fpe_score = max(0, min(100, (40 - req.forward_pe) / 35 * 100))
            value_components.append(fpe_score)
            details["forward_pe_score"] = round(fpe_score, 1)

        if req.peg_ratio is not None and req.peg_ratio > 0:
            # PEG < 1 is undervalued, > 2 is overvalued
            peg_score = max(0, min(100, (2 - req.peg_ratio) / 2 * 100))
            value_components.append(peg_score)
            details["peg_score"] = round(peg_score, 1)

        if req.price_to_book is not None and req.price_to_book > 0:
            pb_score = max(0, min(100, (5 - req.price_to_book) / 5 * 100))
            value_components.append(pb_score)
            details["price_to_book_score"] = round(pb_score, 1)

        if req.current_price is not None and req.target_mean_price is not None:
            if req.current_price > 0:
                upside = (req.target_mean_price - req.current_price) / req.current_price
                upside_score = max(0, min(100, upside / 0.30 * 100))
                value_components.append(upside_score)
                details["upside_score"] = round(upside_score, 1)

        value_score = sum(value_components) / len(value_components) if value_components else 50

        # --- Quality Score (profitability & efficiency) ---
        quality_components = []

        if req.profit_margin is not None:
            # Profit margin: 20%+ excellent, 0% = poor
            pm_score = max(0, min(100, req.profit_margin / 0.25 * 100))
            quality_components.append(pm_score)
            details["profit_margin_score"] = round(pm_score, 1)

        if req.return_on_equity is not None:
            # ROE: 20%+ is excellent
            roe_score = max(0, min(100, req.return_on_equity / 0.25 * 100))
            quality_components.append(roe_score)
            details["roe_score"] = round(roe_score, 1)

        if req.free_cash_flow is not None:
            # Positive FCF is good; higher is better
            fcf_score = 70 if req.free_cash_flow > 0 else 20
            quality_components.append(fcf_score)
            details["fcf_score"] = round(fcf_score, 1)

        quality_score = sum(quality_components) / len(quality_components) if quality_components else 50

        # --- Growth Score ---
        growth_components = []

        if req.revenue_growth is not None:
            rg_score = max(0, min(100, (req.revenue_growth + 0.05) / 0.35 * 100))
            growth_components.append(rg_score)
            details["revenue_growth_score"] = round(rg_score, 1)

        if req.earnings_growth is not None:
            eg_score = max(0, min(100, (req.earnings_growth + 0.05) / 0.35 * 100))
            growth_components.append(eg_score)
            details["earnings_growth_score"] = round(eg_score, 1)

        if req.earnings_per_share is not None and req.earnings_per_share > 0:
            # Positive EPS is baseline good
            growth_components.append(60)

        growth_score = sum(growth_components) / len(growth_components) if growth_components else 50

        # --- Safety Score (debt & risk) ---
        safety_components = []

        if req.debt_to_equity is not None:
            # D/E < 50 is safe, > 200 is risky
            de_score = max(0, min(100, (200 - req.debt_to_equity) / 200 * 100))
            safety_components.append(de_score)
            details["debt_equity_score"] = round(de_score, 1)

        if req.free_cash_flow is not None:
            safety_components.append(75 if req.free_cash_flow > 0 else 25)

        safety_score = sum(safety_components) / len(safety_components) if safety_components else 50

        # --- Composite ---
        composite = (value_score * 0.30 + quality_score * 0.30 + growth_score * 0.20 + safety_score * 0.20)

        return FundamentalScoreResponse(
            ticker=req.ticker,
            value_score=round(value_score, 1),
            quality_score=round(quality_score, 1),
            growth_score=round(growth_score, 1),
            safety_score=round(safety_score, 1),
            composite_score=round(composite, 1),
            details=details,
        )
