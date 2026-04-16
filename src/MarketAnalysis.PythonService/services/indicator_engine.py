import pandas as pd
import pandas_ta as ta
import logging
from typing import Optional

from models.technicals import IndicatorType, IndicatorValue

logger = logging.getLogger(__name__)


class IndicatorEngine:
    """Computes technical indicators using pandas-ta."""

    @staticmethod
    def compute_indicators(
        df: pd.DataFrame,
        indicators: list[IndicatorType],
    ) -> list[IndicatorValue]:
        """
        Compute requested indicators on OHLCV DataFrame.

        Args:
            df: DataFrame with columns: date, open, high, low, close, volume
            indicators: List of indicators to compute

        Returns:
            List of IndicatorValue with date->value mappings
        """
        results: list[IndicatorValue] = []

        # Ensure proper column names (lowercase)
        df.columns = [c.lower() for c in df.columns]
        if "date" in df.columns:
            df = df.set_index("date")
        df.index = pd.to_datetime(df.index)

        for indicator in indicators:
            try:
                values_list = _compute_single_indicator(df, indicator)
                if values_list:
                    results.extend(values_list)
            except Exception as e:
                logger.error(f"Error computing {indicator}: {e}")

        return results


def _compute_single_indicator(df: pd.DataFrame, indicator: IndicatorType) -> Optional[list[IndicatorValue]]:
    """Compute a single indicator and return as list of IndicatorValue objects."""
    date_strs = [d.strftime("%Y-%m-%d") for d in df.index]

    match indicator:
        # --- Moving Averages ---
        case IndicatorType.SMA_20:
            series = ta.sma(df["close"], length=20)
            return [_series_to_indicator("SMA_20", series, date_strs)]

        case IndicatorType.SMA_50:
            series = ta.sma(df["close"], length=50)
            return [_series_to_indicator("SMA_50", series, date_strs)]

        case IndicatorType.SMA_200:
            series = ta.sma(df["close"], length=200)
            return [_series_to_indicator("SMA_200", series, date_strs)]

        case IndicatorType.EMA_9:
            series = ta.ema(df["close"], length=9)
            return [_series_to_indicator("EMA_9", series, date_strs)]

        case IndicatorType.EMA_21:
            series = ta.ema(df["close"], length=21)
            return [_series_to_indicator("EMA_21", series, date_strs)]

        case IndicatorType.EMA_50:
            series = ta.ema(df["close"], length=50)
            return [_series_to_indicator("EMA_50", series, date_strs)]

        # --- Momentum ---
        case IndicatorType.RSI_14:
            series = ta.rsi(df["close"], length=14)
            return [_series_to_indicator("RSI_14", series, date_strs)]

        case IndicatorType.MACD:
            macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
            if macd_df is not None and not macd_df.empty:
                return [
                    _series_to_indicator("MACD", macd_df.iloc[:, 0], date_strs),
                    _series_to_indicator("MACD_SIGNAL", macd_df.iloc[:, 2], date_strs),
                    _series_to_indicator("MACD_HISTOGRAM", macd_df.iloc[:, 1], date_strs),
                ]
            return None

        case IndicatorType.STOCHASTIC:
            stoch_df = ta.stoch(df["high"], df["low"], df["close"], k=14, d=3)
            if stoch_df is not None and not stoch_df.empty:
                return [
                    _series_to_indicator("STOCHASTIC_K", stoch_df.iloc[:, 0], date_strs),
                    _series_to_indicator("STOCHASTIC_D", stoch_df.iloc[:, 1], date_strs),
                ]
            return None

        case IndicatorType.CCI:
            series = ta.cci(df["high"], df["low"], df["close"], length=20)
            return [_series_to_indicator("CCI", series, date_strs)]

        case IndicatorType.WILLIAMS_R:
            series = ta.willr(df["high"], df["low"], df["close"], length=14)
            return [_series_to_indicator("WILLIAMS_R", series, date_strs)]

        # --- Volatility ---
        case IndicatorType.BOLLINGER_BANDS:
            bb_df = ta.bbands(df["close"], length=20, std=2)
            if bb_df is not None and not bb_df.empty:
                return [
                    _series_to_indicator("BB_UPPER", bb_df.iloc[:, 2], date_strs),
                    _series_to_indicator("BB_MIDDLE", bb_df.iloc[:, 1], date_strs),
                    _series_to_indicator("BB_LOWER", bb_df.iloc[:, 0], date_strs),
                ]
            return None

        case IndicatorType.ATR:
            series = ta.atr(df["high"], df["low"], df["close"], length=14)
            return [_series_to_indicator("ATR", series, date_strs)]

        case IndicatorType.ADX:
            adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
            if adx_df is not None and not adx_df.empty:
                return [
                    _series_to_indicator("ADX", adx_df.iloc[:, 0], date_strs),
                    _series_to_indicator("ADX_POS_DI", adx_df.iloc[:, 1], date_strs),
                    _series_to_indicator("ADX_NEG_DI", adx_df.iloc[:, 2], date_strs),
                ]
            return None

        # --- Volume ---
        case IndicatorType.OBV:
            series = ta.obv(df["close"], df["volume"])
            return [_series_to_indicator("OBV", series, date_strs)]

        case IndicatorType.VWAP:
            if "volume" in df.columns:
                series = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
                return [_series_to_indicator("VWAP", series, date_strs)]
            return None

        case IndicatorType.VOLUME_SMA:
            series = ta.sma(df["volume"], length=20)
            return [_series_to_indicator("VOLUME_SMA_20", series, date_strs)]

    return None


def _series_to_indicator(name: str, series: Optional[pd.Series], date_strs: list[str]) -> Optional[IndicatorValue]:
    """Convert a pandas Series to an IndicatorValue."""
    if series is None:
        return None

    values: dict[str, Optional[float]] = {}
    for i, date_str in enumerate(date_strs):
        if i < len(series):
            val = series.iloc[i]
            values[date_str] = round(float(val), 4) if pd.notna(val) else None
        else:
            values[date_str] = None

    return IndicatorValue(name=name, values=values)
