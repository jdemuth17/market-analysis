"""AI-powered analyst report generation using Ollama Cloud."""

import logging
import json
from services.ollama_client import OllamaClient
from models.ai_analysis import AnalystReportResponse, TradeLevelResponse
from config import get_settings
from typing import Any

logger = logging.getLogger(__name__)


class AiReportGenerator:
    """Generates structured analyst reports using deepseek-v3.2."""

    def __init__(self, ollama_client: OllamaClient):
        self._ollama = ollama_client
        self._settings = get_settings()

    async def generate_report(self, request: Any) -> AnalystReportResponse:
        """Generate full analyst report with trade levels."""
        prompt = self._build_prompt(request)
        
        system_msg = {
            "role": "system",
            "content": "You are a senior financial analyst with 20 years of experience in equity research. Provide comprehensive analysis with specific, actionable insights. Base recommendations on technical patterns, fundamental metrics, and sentiment signals."
        }
        user_msg = {"role": "user", "content": prompt}
        
        try:
            response = await self._ollama.chat(
                model=self._settings.ollama_reasoning_model,
                messages=[system_msg, user_msg],
                format_schema=AnalystReportResponse.model_json_schema()
            )
            
            content = response.get("message", {}).get("content", "{}")
            report_data = json.loads(content)
            report = AnalystReportResponse(**report_data)
            
            if not self._validate_trade_levels(report.trade_levels):
                raise ValueError("Invalid trade levels: stop_loss must be < entry < profit_target")
            
            return report
        except Exception as e:
            logger.error(f"Failed to generate AI report: {e}")
            raise

    def _build_prompt(self, request: Any) -> str:
        """Build analysis prompt from ticker context."""
        ticker = request.ticker
        
        price_summary = self._summarize_price_history(request.price_history)
        technical_summary = self._summarize_technicals(request.technicals)
        fundamental_summary = self._summarize_fundamentals(request.fundamentals)
        sentiment_summary = self._summarize_sentiment(request.sentiment)
        
        prompt = f"""Analyze {ticker} and provide a comprehensive report.

PRICE DATA (last 30 bars):
{price_summary}

TECHNICAL ANALYSIS:
{technical_summary}

FUNDAMENTALS:
{fundamental_summary}

SENTIMENT:
{sentiment_summary}

Provide:
1. Summary: 2-3 sentence overview of current position
2. Outlook: Bullish/Bearish/Neutral with 1-2 sentence rationale
3. Key Factors: 3-5 bullish points
4. Risk Factors: 3-5 bearish points
5. Recommendation: Buy/Hold/Sell with confidence (0-1)
6. Trade Levels: Entry, stop-loss, profit target, exit price with rationale

Be specific with price levels based on support/resistance and current price action.
"""
        return prompt

    def _summarize_price_history(self, price_history: list[dict]) -> str:
        """Truncate and format price history."""
        bars = price_history[-self._settings.ai_price_bar_count:]
        if not bars:
            return "No price data available"
        
        lines = ["Date\tOpen\tHigh\tLow\tClose\tVolume"]
        for bar in bars[-10:]:
            lines.append(f"{bar.get('date', 'N/A')}\t{bar.get('open', 0):.2f}\t{bar.get('high', 0):.2f}\t{bar.get('low', 0):.2f}\t{bar.get('close', 0):.2f}\t{bar.get('volume', 0)}")
        
        current = bars[-1].get('close', 0)
        prev = bars[-2].get('close', 0) if len(bars) > 1 else current
        change_pct = ((current - prev) / prev * 100) if prev > 0 else 0
        
        lines.append(f"\nCurrent: ${current:.2f} ({change_pct:+.2f}%)")
        return "\n".join(lines)

    def _summarize_technicals(self, technicals: dict) -> str:
        """Extract key technical signals."""
        patterns = technicals.get('detected_patterns', [])
        indicators = technicals.get('indicators', {})
        
        lines = []
        if patterns:
            lines.append(f"Patterns: {', '.join([p.get('pattern_type', 'unknown') for p in patterns[:3]])}")
        
        if 'rsi_14' in indicators:
            lines.append(f"RSI(14): {indicators['rsi_14']:.1f}")
        if 'macd' in indicators:
            lines.append(f"MACD: {indicators['macd']:.2f}")
        
        return "\n".join(lines) if lines else "No technical data"

    def _summarize_fundamentals(self, fundamentals: dict) -> str:
        """Extract key fundamental metrics."""
        lines = []
        for key in ['pe_ratio', 'forward_pe', 'debt_to_equity', 'profit_margin', 'roe']:
            if key in fundamentals and fundamentals[key] is not None:
                lines.append(f"{key.upper()}: {fundamentals[key]:.2f}")
        return "\n".join(lines) if lines else "No fundamental data"

    def _summarize_sentiment(self, sentiment: dict) -> str:
        """Extract sentiment scores."""
        return f"Positive: {sentiment.get('positive_score', 0):.2f}, Negative: {sentiment.get('negative_score', 0):.2f}, Neutral: {sentiment.get('neutral_score', 0):.2f}"

    def _validate_trade_levels(self, levels: TradeLevelResponse) -> bool:
        """Validate trade level logic."""
        return (levels.stop_loss > 0 and levels.entry > 0 and levels.profit_target > 0 and
                levels.stop_loss < levels.entry < levels.profit_target)
