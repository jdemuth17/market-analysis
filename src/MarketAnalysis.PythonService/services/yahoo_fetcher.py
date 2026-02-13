import yfinance as yf
import pandas as pd
import logging
import time
from datetime import date
from typing import Optional

from models.market_data import (
    OHLCVBar, TickerPriceData, FetchPricesResponse,
    FundamentalData, FetchFundamentalsResponse,
)
from utils.rate_limiter import yahoo_rate_limiter

logger = logging.getLogger(__name__)


class YahooFetcher:
    """Wrapper around yfinance with rate limiting and error handling."""

    @staticmethod
    def fetch_prices(
        tickers: list[str],
        period: str = "6mo",
        interval: str = "1d",
    ) -> FetchPricesResponse:
        """Fetch OHLCV data for multiple tickers using bulk download."""
        results: list[TickerPriceData] = []
        successful = 0
        failed = 0

        # Process in chunks to respect rate limits
        chunk_size = 50
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i : i + chunk_size]
            yahoo_rate_limiter.wait()

            try:
                logger.info(f"Downloading prices for {len(chunk)} tickers (chunk {i // chunk_size + 1})")
                df = yf.download(
                    tickers=chunk,
                    period=period,
                    interval=interval,
                    group_by="ticker",
                    auto_adjust=False,
                    threads=True,
                    progress=False,
                )

                if df.empty:
                    for t in chunk:
                        results.append(TickerPriceData(ticker=t, bars=[], error="No data returned"))
                        failed += 1
                    continue

                for ticker in chunk:
                    try:
                        # yfinance 1.x always returns multi-level columns: (ticker, price_col)
                        # with group_by="ticker", level 0 = ticker name
                        if ticker not in df.columns.get_level_values(0):
                            results.append(TickerPriceData(ticker=ticker, bars=[], error="Ticker not in response"))
                            failed += 1
                            continue
                        ticker_df = df[ticker].copy()

                        ticker_df = ticker_df.dropna(subset=["Close"])
                        bars = []
                        for idx, row in ticker_df.iterrows():
                            bar_date = idx.date() if hasattr(idx, "date") else idx
                            bars.append(OHLCVBar(
                                date=bar_date,
                                open=round(float(row.get("Open", 0)), 4),
                                high=round(float(row.get("High", 0)), 4),
                                low=round(float(row.get("Low", 0)), 4),
                                close=round(float(row.get("Close", 0)), 4),
                                adj_close=round(float(row.get("Adj Close", row.get("Close", 0))), 4),
                                volume=int(row.get("Volume", 0)),
                            ))

                        results.append(TickerPriceData(ticker=ticker, bars=bars))
                        successful += 1

                    except Exception as e:
                        logger.error(f"Error processing {ticker}: {e}")
                        results.append(TickerPriceData(ticker=ticker, bars=[], error=str(e)))
                        failed += 1

            except Exception as e:
                logger.error(f"Bulk download error for chunk: {e}")
                for t in chunk:
                    results.append(TickerPriceData(ticker=t, bars=[], error=str(e)))
                    failed += 1

            # Delay between chunks
            if i + chunk_size < len(tickers):
                time.sleep(1.0)

        return FetchPricesResponse(
            data=results,
            total_tickers=len(tickers),
            successful=successful,
            failed=failed,
        )

    @staticmethod
    def _fetch_single_fundamental(ticker_symbol: str) -> FundamentalData:
        """Fetch fundamental data for a single ticker. Used by ThreadPoolExecutor."""
        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info

            if not info or "symbol" not in info:
                return FundamentalData(ticker=ticker_symbol, error="No info returned")

            return FundamentalData(
                ticker=ticker_symbol,
                company_name=info.get("longName") or info.get("shortName"),
                sector=info.get("sector"),
                industry=info.get("industry"),
                exchange=info.get("exchange"),
                pe_ratio=_safe_float(info.get("trailingPE")),
                forward_pe=_safe_float(info.get("forwardPE")),
                peg_ratio=_safe_float(info.get("pegRatio")),
                price_to_book=_safe_float(info.get("priceToBook")),
                revenue_per_share=_safe_float(info.get("revenuePerShare")),
                earnings_per_share=_safe_float(info.get("trailingEps")),
                debt_to_equity=_safe_float(info.get("debtToEquity")),
                profit_margin=_safe_float(info.get("profitMargins")),
                operating_margin=_safe_float(info.get("operatingMargins")),
                return_on_equity=_safe_float(info.get("returnOnEquity")),
                free_cash_flow=_safe_float(info.get("freeCashflow")),
                dividend_yield=_safe_float(info.get("dividendYield")),
                revenue=_safe_float(info.get("totalRevenue")),
                market_cap=_safe_float(info.get("marketCap")),
                beta=_safe_float(info.get("beta")),
                fifty_two_week_high=_safe_float(info.get("fiftyTwoWeekHigh")),
                fifty_two_week_low=_safe_float(info.get("fiftyTwoWeekLow")),
                current_price=_safe_float(info.get("currentPrice") or info.get("regularMarketPrice")),
                target_mean_price=_safe_float(info.get("targetMeanPrice")),
                recommendation_key=info.get("recommendationKey"),
                raw_info=info,
            )

        except Exception as e:
            logger.error(f"Error fetching fundamentals for {ticker_symbol}: {e}")
            return FundamentalData(ticker=ticker_symbol, error=str(e))

    @staticmethod
    def fetch_fundamentals(tickers: list[str]) -> FetchFundamentalsResponse:
        """Fetch fundamental data for multiple tickers using parallel threads."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: list[FundamentalData] = []
        successful = 0
        failed = 0

        # Use 10 parallel workers — Yahoo tolerates moderate concurrency
        max_workers = 10
        logger.info(f"Fetching fundamentals for {len(tickers)} tickers ({max_workers} parallel workers)")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ticker = {
                executor.submit(YahooFetcher._fetch_single_fundamental, t): t
                for t in tickers
            }

            for future in as_completed(future_to_ticker):
                result = future.result()
                results.append(result)
                if result.error is None:
                    successful += 1
                else:
                    failed += 1

        return FetchFundamentalsResponse(
            data=results,
            total_tickers=len(tickers),
            successful=successful,
            failed=failed,
        )


def _safe_float(value) -> Optional[float]:
    """Safely convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        result = float(value)
        if pd.isna(result):
            return None
        return result
    except (ValueError, TypeError):
        return None
