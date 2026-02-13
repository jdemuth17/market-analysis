import os
import pandas as pd
import requests
import certifi
import logging
import time
import json
from io import StringIO
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}


def _fetch_html(url: str) -> str:
    """Fetch HTML from a URL with a proper User-Agent header."""
    resp = requests.get(url, headers=_HEADERS, timeout=30, verify=certifi.where())
    resp.raise_for_status()
    return resp.text

CACHE_DIR = Path(__file__).parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)


def _get_cache_path(index_name: str) -> Path:
    return CACHE_DIR / f"{index_name}_tickers.json"


def _is_cache_valid(cache_path: Path, max_age_hours: int = 168) -> bool:
    if not cache_path.exists():
        return False
    modified = datetime.fromtimestamp(cache_path.stat().st_mtime)
    return datetime.now() - modified < timedelta(hours=max_age_hours)


def get_sp500_tickers(use_cache: bool = True) -> list[str]:
    """Get S&P 500 tickers from Wikipedia, with caching."""
    cache_path = _get_cache_path("sp500")

    if use_cache and _is_cache_valid(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        html = _fetch_html(url)
        tables = pd.read_html(StringIO(html))
        df = tables[0]
        tickers = sorted(df["Symbol"].str.replace(".", "-", regex=False).tolist())

        with open(cache_path, "w") as f:
            json.dump(tickers, f)

        logger.info(f"Fetched {len(tickers)} S&P 500 tickers from Wikipedia")
        return tickers

    except Exception as e:
        logger.error(f"Failed to fetch S&P 500 tickers: {e}")
        if cache_path.exists():
            with open(cache_path) as f:
                return json.load(f)
        return []


def get_nasdaq100_tickers(use_cache: bool = True) -> list[str]:
    """Get NASDAQ 100 tickers from Wikipedia, with caching."""
    cache_path = _get_cache_path("nasdaq100")

    if use_cache and _is_cache_valid(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    try:
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        html = _fetch_html(url)
        tables = pd.read_html(StringIO(html))
        # The ticker table is usually the 4th table on the page
        for table in tables:
            if "Ticker" in table.columns:
                tickers = sorted(table["Ticker"].str.replace(".", "-", regex=False).tolist())
                with open(cache_path, "w") as f:
                    json.dump(tickers, f)
                logger.info(f"Fetched {len(tickers)} NASDAQ 100 tickers from Wikipedia")
                return tickers

        # Fallback: try 'Symbol' column
        for table in tables:
            if "Symbol" in table.columns:
                tickers = sorted(table["Symbol"].str.replace(".", "-", regex=False).tolist())
                with open(cache_path, "w") as f:
                    json.dump(tickers, f)
                logger.info(f"Fetched {len(tickers)} NASDAQ 100 tickers from Wikipedia")
                return tickers

        logger.warning("Could not find ticker column in NASDAQ 100 Wikipedia tables")
        return []

    except Exception as e:
        logger.error(f"Failed to fetch NASDAQ 100 tickers: {e}")
        if cache_path.exists():
            with open(cache_path) as f:
                return json.load(f)
        return []


def get_nasdaq_all_tickers(use_cache: bool = True) -> list[str]:
    """
    Get ALL NASDAQ-listed tickers from the official NASDAQ Trader symbol directory.
    This returns ~3,300 stocks (all common stocks, excluding ETFs/warrants/test issues).
    """
    cache_path = _get_cache_path("nasdaq_all")

    if use_cache and _is_cache_valid(cache_path, max_age_hours=24):  # Shorter cache for full list
        with open(cache_path) as f:
            return json.load(f)

    try:
        # Official NASDAQ FTP symbol directory (accessible via HTTPS)
        url = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
        resp = requests.get(url, headers=_HEADERS, timeout=30, verify=certifi.where())
        resp.raise_for_status()

        # Parse pipe-delimited file (skip header and footer)
        lines = resp.text.strip().split('\n')
        tickers = []

        for line in lines[1:]:  # Skip header
            if '|' not in line:
                continue
            parts = line.split('|')
            if len(parts) < 7:
                continue

            symbol = parts[0].strip()
            test_issue = parts[3].strip()  # 'Y' = test issue
            etf = parts[5].strip()  # 'Y' = ETF

            # Skip test issues, ETFs, and symbols with special characters
            if test_issue == 'Y' or etf == 'Y':
                continue
            if not symbol or symbol.startswith('File Creation'):
                continue
            if any(c in symbol for c in ['^', '$', '.', ' ']):
                continue

            tickers.append(symbol)

        tickers = sorted(set(tickers))

        with open(cache_path, "w") as f:
            json.dump(tickers, f)

        logger.info(f"Fetched {len(tickers)} NASDAQ tickers from nasdaqtrader.com")
        return tickers

    except Exception as e:
        logger.error(f"Failed to fetch NASDAQ tickers: {e}")
        if cache_path.exists():
            with open(cache_path) as f:
                return json.load(f)
        return []


def get_tickers_for_index(index_name: str) -> list[str]:
    """Get tickers for a named index."""
    index_map = {
        "sp500": get_sp500_tickers,
        "nasdaq100": get_nasdaq100_tickers,
        "nasdaq": get_nasdaq_all_tickers,
        "nasdaq_all": get_nasdaq_all_tickers,
    }
    fn = index_map.get(index_name.lower())
    if fn:
        return fn()
    raise ValueError(f"Unknown index: {index_name}. Available: {list(index_map.keys())}")
