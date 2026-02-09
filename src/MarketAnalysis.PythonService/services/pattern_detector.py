"""
Custom chart pattern detection using pivot-point identification and geometric rule validation.

Detects: Double Top, Double Bottom, Head & Shoulders (and inverse), Bull/Bear Flag,
Ascending/Descending/Symmetrical Triangle, Rising/Falling Wedge, Pennant, Cup and Handle.
"""

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema
import logging
from datetime import date
from typing import Optional

from models.technicals import (
    PatternType, SignalDirection, PatternStatus, DetectedPattern,
)

logger = logging.getLogger(__name__)


class PatternDetector:
    """Detects chart patterns in OHLCV price data."""

    def __init__(self, df: pd.DataFrame, lookback_days: int = 120):
        """
        Args:
            df: DataFrame with columns: date, open, high, low, close, volume
            lookback_days: Number of bars to analyze
        """
        self.df = df.copy()
        self.df.columns = [c.lower() for c in self.df.columns]

        if "date" in self.df.columns:
            self.df["date"] = pd.to_datetime(self.df["date"])
            self.df = self.df.set_index("date")

        # Trim to lookback period
        self.df = self.df.tail(lookback_days)
        self.close = self.df["close"].values.astype(float)
        self.high = self.df["high"].values.astype(float)
        self.low = self.df["low"].values.astype(float)
        self.volume = self.df["volume"].values.astype(float)
        self.dates = self.df.index.tolist()
        self.n = len(self.close)

        # Identify pivots
        self._find_pivots()

    def _find_pivots(self, order: int = 5):
        """Find local highs and lows using argrelextrema."""
        if self.n < order * 2 + 1:
            self.pivot_high_idx = np.array([], dtype=int)
            self.pivot_low_idx = np.array([], dtype=int)
            return

        self.pivot_high_idx = argrelextrema(self.high, np.greater_equal, order=order)[0]
        self.pivot_low_idx = argrelextrema(self.low, np.less_equal, order=order)[0]

        self.pivot_highs = self.high[self.pivot_high_idx]
        self.pivot_lows = self.low[self.pivot_low_idx]

    def _to_date(self, idx: int) -> date:
        """Convert array index to date."""
        dt = self.dates[idx]
        if hasattr(dt, "date"):
            return dt.date()
        return dt

    def detect_patterns(self, patterns: list[PatternType]) -> list[DetectedPattern]:
        """Run detection for requested patterns."""
        results: list[DetectedPattern] = []

        detector_map = {
            PatternType.DOUBLE_TOP: self._detect_double_top,
            PatternType.DOUBLE_BOTTOM: self._detect_double_bottom,
            PatternType.HEAD_AND_SHOULDERS: self._detect_head_and_shoulders,
            PatternType.INVERSE_HEAD_AND_SHOULDERS: self._detect_inverse_head_and_shoulders,
            PatternType.BULL_FLAG: self._detect_bull_flag,
            PatternType.BEAR_FLAG: self._detect_bear_flag,
            PatternType.ASCENDING_TRIANGLE: self._detect_ascending_triangle,
            PatternType.DESCENDING_TRIANGLE: self._detect_descending_triangle,
            PatternType.SYMMETRICAL_TRIANGLE: self._detect_symmetrical_triangle,
            PatternType.RISING_WEDGE: self._detect_rising_wedge,
            PatternType.FALLING_WEDGE: self._detect_falling_wedge,
            PatternType.PENNANT: self._detect_pennant,
            PatternType.CUP_AND_HANDLE: self._detect_cup_and_handle,
        }

        for pattern in patterns:
            fn = detector_map.get(pattern)
            if fn:
                try:
                    detected = fn()
                    if detected:
                        results.extend(detected if isinstance(detected, list) else [detected])
                except Exception as e:
                    logger.error(f"Error detecting {pattern}: {e}")

        return results

    # ---------- Double Top ----------
    def _detect_double_top(self) -> list[DetectedPattern]:
        """Two peaks at similar levels with a trough between them."""
        results = []
        if len(self.pivot_high_idx) < 2:
            return results

        tolerance = 0.03  # 3% price tolerance between peaks

        for i in range(len(self.pivot_high_idx) - 1):
            for j in range(i + 1, len(self.pivot_high_idx)):
                idx1, idx2 = self.pivot_high_idx[i], self.pivot_high_idx[j]
                peak1, peak2 = self.high[idx1], self.high[idx2]

                # Peaks should be at similar level
                if abs(peak1 - peak2) / max(peak1, peak2) > tolerance:
                    continue

                # Must have some separation (at least 10 bars)
                if idx2 - idx1 < 10:
                    continue

                # Find the lowest trough between the two peaks
                trough_region = self.low[idx1:idx2 + 1]
                trough_idx_local = np.argmin(trough_region)
                trough_idx = idx1 + trough_idx_local
                neckline = self.low[trough_idx]

                # Trough should be meaningfully lower than peaks (at least 2%)
                avg_peak = (peak1 + peak2) / 2
                if (avg_peak - neckline) / avg_peak < 0.02:
                    continue

                # Check if price has broken below neckline after 2nd peak
                remaining = self.close[idx2:]
                status = PatternStatus.FORMING
                if len(remaining) > 0 and np.any(remaining < neckline):
                    status = PatternStatus.CONFIRMED

                # Confidence based on symmetry and depth
                symmetry = 1 - abs(peak1 - peak2) / max(peak1, peak2) / tolerance
                depth = min((avg_peak - neckline) / avg_peak / 0.10, 1.0)
                confidence = min(symmetry * 50 + depth * 50, 100)

                target = neckline - (avg_peak - neckline)

                results.append(DetectedPattern(
                    pattern_type=PatternType.DOUBLE_TOP,
                    direction=SignalDirection.BEARISH,
                    confidence=round(confidence, 1),
                    start_date=self._to_date(idx1),
                    end_date=self._to_date(min(idx2 + 5, self.n - 1)),
                    key_levels={"resistance": round(avg_peak, 2), "neckline": round(neckline, 2), "target": round(target, 2)},
                    status=status,
                ))

        return results[:3]  # Return top 3 at most

    # ---------- Double Bottom ----------
    def _detect_double_bottom(self) -> list[DetectedPattern]:
        """Two troughs at similar levels with a peak between them."""
        results = []
        if len(self.pivot_low_idx) < 2:
            return results

        tolerance = 0.03

        for i in range(len(self.pivot_low_idx) - 1):
            for j in range(i + 1, len(self.pivot_low_idx)):
                idx1, idx2 = self.pivot_low_idx[i], self.pivot_low_idx[j]
                trough1, trough2 = self.low[idx1], self.low[idx2]

                if abs(trough1 - trough2) / max(trough1, trough2) > tolerance:
                    continue

                if idx2 - idx1 < 10:
                    continue

                # Find highest peak between troughs
                peak_region = self.high[idx1:idx2 + 1]
                peak_idx_local = np.argmax(peak_region)
                peak_idx = idx1 + peak_idx_local
                neckline = self.high[peak_idx]

                avg_trough = (trough1 + trough2) / 2
                if (neckline - avg_trough) / neckline < 0.02:
                    continue

                remaining = self.close[idx2:]
                status = PatternStatus.FORMING
                if len(remaining) > 0 and np.any(remaining > neckline):
                    status = PatternStatus.CONFIRMED

                symmetry = 1 - abs(trough1 - trough2) / max(trough1, trough2) / tolerance
                depth = min((neckline - avg_trough) / neckline / 0.10, 1.0)
                confidence = min(symmetry * 50 + depth * 50, 100)

                target = neckline + (neckline - avg_trough)

                results.append(DetectedPattern(
                    pattern_type=PatternType.DOUBLE_BOTTOM,
                    direction=SignalDirection.BULLISH,
                    confidence=round(confidence, 1),
                    start_date=self._to_date(idx1),
                    end_date=self._to_date(min(idx2 + 5, self.n - 1)),
                    key_levels={"support": round(avg_trough, 2), "neckline": round(neckline, 2), "target": round(target, 2)},
                    status=status,
                ))

        return results[:3]

    # ---------- Head & Shoulders ----------
    def _detect_head_and_shoulders(self) -> list[DetectedPattern]:
        """Three peaks: middle highest, shoulders at similar heights."""
        results = []
        if len(self.pivot_high_idx) < 3:
            return results

        for i in range(len(self.pivot_high_idx) - 2):
            idx_ls, idx_h, idx_rs = self.pivot_high_idx[i], self.pivot_high_idx[i + 1], self.pivot_high_idx[i + 2]
            ls, h, rs = self.high[idx_ls], self.high[idx_h], self.high[idx_rs]

            # Head must be the highest
            if h <= ls or h <= rs:
                continue

            # Shoulders should be at similar levels (within 5%)
            if abs(ls - rs) / max(ls, rs) > 0.05:
                continue

            # Head should be meaningfully higher than shoulders (at least 2%)
            avg_shoulder = (ls + rs) / 2
            if (h - avg_shoulder) / h < 0.02:
                continue

            # Neckline: connect the lows between left shoulder-head and head-right shoulder
            trough1_region = self.low[idx_ls:idx_h + 1]
            trough2_region = self.low[idx_h:idx_rs + 1]
            neckline_left = self.low[idx_ls + np.argmin(trough1_region)]
            neckline_right = self.low[idx_h + np.argmin(trough2_region)]
            neckline = (neckline_left + neckline_right) / 2

            remaining = self.close[idx_rs:]
            status = PatternStatus.FORMING
            if len(remaining) > 0 and np.any(remaining < neckline):
                status = PatternStatus.CONFIRMED

            shoulder_symmetry = 1 - abs(ls - rs) / max(ls, rs) / 0.05
            head_prominence = min((h - avg_shoulder) / h / 0.05, 1.0)
            confidence = min(shoulder_symmetry * 40 + head_prominence * 40 + 20, 100)

            target = neckline - (h - neckline)

            results.append(DetectedPattern(
                pattern_type=PatternType.HEAD_AND_SHOULDERS,
                direction=SignalDirection.BEARISH,
                confidence=round(confidence, 1),
                start_date=self._to_date(idx_ls),
                end_date=self._to_date(min(idx_rs + 5, self.n - 1)),
                key_levels={
                    "left_shoulder": round(ls, 2), "head": round(h, 2), "right_shoulder": round(rs, 2),
                    "neckline": round(neckline, 2), "target": round(target, 2),
                },
                status=status,
            ))

        return results[:2]

    # ---------- Inverse Head & Shoulders ----------
    def _detect_inverse_head_and_shoulders(self) -> list[DetectedPattern]:
        """Three troughs: middle lowest, shoulders at similar depths."""
        results = []
        if len(self.pivot_low_idx) < 3:
            return results

        for i in range(len(self.pivot_low_idx) - 2):
            idx_ls, idx_h, idx_rs = self.pivot_low_idx[i], self.pivot_low_idx[i + 1], self.pivot_low_idx[i + 2]
            ls, h, rs = self.low[idx_ls], self.low[idx_h], self.low[idx_rs]

            # Head must be the lowest
            if h >= ls or h >= rs:
                continue

            if abs(ls - rs) / max(ls, rs) > 0.05:
                continue

            avg_shoulder = (ls + rs) / 2
            if (avg_shoulder - h) / avg_shoulder < 0.02:
                continue

            # Neckline from peaks between shoulders
            peak1_region = self.high[idx_ls:idx_h + 1]
            peak2_region = self.high[idx_h:idx_rs + 1]
            neckline_left = self.high[idx_ls + np.argmax(peak1_region)]
            neckline_right = self.high[idx_h + np.argmax(peak2_region)]
            neckline = (neckline_left + neckline_right) / 2

            remaining = self.close[idx_rs:]
            status = PatternStatus.FORMING
            if len(remaining) > 0 and np.any(remaining > neckline):
                status = PatternStatus.CONFIRMED

            shoulder_symmetry = 1 - abs(ls - rs) / max(ls, rs) / 0.05
            head_prominence = min((avg_shoulder - h) / avg_shoulder / 0.05, 1.0)
            confidence = min(shoulder_symmetry * 40 + head_prominence * 40 + 20, 100)

            target = neckline + (neckline - h)

            results.append(DetectedPattern(
                pattern_type=PatternType.INVERSE_HEAD_AND_SHOULDERS,
                direction=SignalDirection.BULLISH,
                confidence=round(confidence, 1),
                start_date=self._to_date(idx_ls),
                end_date=self._to_date(min(idx_rs + 5, self.n - 1)),
                key_levels={
                    "left_shoulder": round(ls, 2), "head": round(h, 2), "right_shoulder": round(rs, 2),
                    "neckline": round(neckline, 2), "target": round(target, 2),
                },
                status=status,
            ))

        return results[:2]

    # ---------- Flag Patterns ----------
    def _detect_flag(self, bullish: bool) -> list[DetectedPattern]:
        """Detect bull or bear flag: strong move (pole) + consolidation channel."""
        results = []
        min_pole_bars = 5
        min_flag_bars = 5
        max_flag_bars = 25
        min_pole_move_pct = 0.05  # 5% minimum pole move

        for pole_start in range(0, self.n - min_pole_bars - min_flag_bars, 3):
            for pole_end in range(pole_start + min_pole_bars, min(pole_start + 30, self.n - min_flag_bars)):
                pole_move = (self.close[pole_end] - self.close[pole_start]) / self.close[pole_start]

                # Check direction matches pattern type
                if bullish and pole_move < min_pole_move_pct:
                    continue
                if not bullish and pole_move > -min_pole_move_pct:
                    continue

                # Flag region: consolidation after pole
                flag_end = min(pole_end + max_flag_bars, self.n - 1)
                flag_region = self.close[pole_end:flag_end + 1]
                if len(flag_region) < min_flag_bars:
                    continue

                # Flag should consolidate: range < 50% of pole height
                flag_range = np.max(self.high[pole_end:flag_end + 1]) - np.min(self.low[pole_end:flag_end + 1])
                pole_height = abs(self.close[pole_end] - self.close[pole_start])
                if pole_height == 0:
                    continue

                if flag_range / pole_height > 0.50:
                    continue

                # Flag should slope against the pole (slight counter-trend)
                flag_slope = np.polyfit(range(len(flag_region)), flag_region, 1)[0]
                if bullish and flag_slope > 0:
                    continue  # Should slope down or flat for bull flag
                if not bullish and flag_slope < 0:
                    continue  # Should slope up or flat for bear flag

                # Volume should decrease during flag
                pole_vol_avg = np.mean(self.volume[pole_start:pole_end + 1])
                flag_vol_avg = np.mean(self.volume[pole_end:flag_end + 1])
                vol_decrease = flag_vol_avg < pole_vol_avg

                # Confidence
                consolidation_tightness = 1 - min(flag_range / pole_height / 0.50, 1.0)
                pole_strength = min(abs(pole_move) / min_pole_move_pct / 2, 1.0)
                vol_score = 0.8 if vol_decrease else 0.4
                confidence = min(consolidation_tightness * 30 + pole_strength * 40 + vol_score * 30, 100)

                if confidence < 40:
                    continue

                pattern_type = PatternType.BULL_FLAG if bullish else PatternType.BEAR_FLAG
                direction = SignalDirection.BULLISH if bullish else SignalDirection.BEARISH
                target = self.close[flag_end] + pole_height if bullish else self.close[flag_end] - pole_height

                results.append(DetectedPattern(
                    pattern_type=pattern_type,
                    direction=direction,
                    confidence=round(confidence, 1),
                    start_date=self._to_date(pole_start),
                    end_date=self._to_date(flag_end),
                    key_levels={
                        "pole_start": round(self.close[pole_start], 2),
                        "pole_end": round(self.close[pole_end], 2),
                        "flag_high": round(float(np.max(self.high[pole_end:flag_end + 1])), 2),
                        "flag_low": round(float(np.min(self.low[pole_end:flag_end + 1])), 2),
                        "target": round(target, 2),
                    },
                    status=PatternStatus.FORMING,
                ))

                break  # Found flag for this pole_start

        # Sort by confidence and return top results
        results.sort(key=lambda x: x.confidence, reverse=True)
        return results[:3]

    def _detect_bull_flag(self) -> list[DetectedPattern]:
        return self._detect_flag(bullish=True)

    def _detect_bear_flag(self) -> list[DetectedPattern]:
        return self._detect_flag(bullish=False)

    # ---------- Triangle Patterns ----------
    def _fit_trendline(self, indices: np.ndarray, prices: np.ndarray) -> tuple[float, float]:
        """Fit a linear trendline. Returns (slope, intercept)."""
        if len(indices) < 2:
            return (0.0, prices[0] if len(prices) > 0 else 0.0)
        coeffs = np.polyfit(indices, prices, 1)
        return (coeffs[0], coeffs[1])

    def _detect_ascending_triangle(self) -> list[DetectedPattern]:
        """Flat resistance + rising support (higher lows)."""
        results = []
        if len(self.pivot_high_idx) < 2 or len(self.pivot_low_idx) < 2:
            return results

        # Check if resistance is relatively flat
        res_slope, res_intercept = self._fit_trendline(self.pivot_high_idx, self.pivot_highs)
        sup_slope, sup_intercept = self._fit_trendline(self.pivot_low_idx, self.pivot_lows)

        # Ascending triangle: flat top (small slope), rising bottom (positive slope)
        price_range = np.max(self.high) - np.min(self.low)
        if price_range == 0:
            return results

        res_slope_norm = res_slope / price_range * self.n
        sup_slope_norm = sup_slope / price_range * self.n

        if abs(res_slope_norm) < 0.15 and sup_slope_norm > 0.05:
            resistance = float(np.mean(self.pivot_highs[-3:]) if len(self.pivot_highs) >= 3 else np.mean(self.pivot_highs))
            support_current = float(self.pivot_lows[-1]) if len(self.pivot_lows) > 0 else float(np.min(self.low))

            # Converging lines
            confidence_flatness = max(0, 1 - abs(res_slope_norm) / 0.15) * 30
            confidence_rising = min(sup_slope_norm / 0.15, 1.0) * 30
            touches_res = min(len(self.pivot_high_idx), 4) / 4 * 20
            touches_sup = min(len(self.pivot_low_idx), 4) / 4 * 20
            confidence = min(confidence_flatness + confidence_rising + touches_res + touches_sup, 100)

            if confidence >= 40:
                target = resistance + (resistance - support_current)
                results.append(DetectedPattern(
                    pattern_type=PatternType.ASCENDING_TRIANGLE,
                    direction=SignalDirection.BULLISH,
                    confidence=round(confidence, 1),
                    start_date=self._to_date(min(self.pivot_high_idx[0], self.pivot_low_idx[0])),
                    end_date=self._to_date(self.n - 1),
                    key_levels={"resistance": round(resistance, 2), "support": round(support_current, 2), "target": round(target, 2)},
                    status=PatternStatus.FORMING,
                ))

        return results

    def _detect_descending_triangle(self) -> list[DetectedPattern]:
        """Flat support + falling resistance (lower highs)."""
        results = []
        if len(self.pivot_high_idx) < 2 or len(self.pivot_low_idx) < 2:
            return results

        res_slope, _ = self._fit_trendline(self.pivot_high_idx, self.pivot_highs)
        sup_slope, _ = self._fit_trendline(self.pivot_low_idx, self.pivot_lows)

        price_range = np.max(self.high) - np.min(self.low)
        if price_range == 0:
            return results

        res_slope_norm = res_slope / price_range * self.n
        sup_slope_norm = sup_slope / price_range * self.n

        if res_slope_norm < -0.05 and abs(sup_slope_norm) < 0.15:
            support = float(np.mean(self.pivot_lows[-3:]) if len(self.pivot_lows) >= 3 else np.mean(self.pivot_lows))
            resistance_current = float(self.pivot_highs[-1]) if len(self.pivot_highs) > 0 else float(np.max(self.high))

            confidence_flatness = max(0, 1 - abs(sup_slope_norm) / 0.15) * 30
            confidence_falling = min(abs(res_slope_norm) / 0.15, 1.0) * 30
            touches = min(len(self.pivot_high_idx) + len(self.pivot_low_idx), 8) / 8 * 40
            confidence = min(confidence_flatness + confidence_falling + touches, 100)

            if confidence >= 40:
                target = support - (resistance_current - support)
                results.append(DetectedPattern(
                    pattern_type=PatternType.DESCENDING_TRIANGLE,
                    direction=SignalDirection.BEARISH,
                    confidence=round(confidence, 1),
                    start_date=self._to_date(min(self.pivot_high_idx[0], self.pivot_low_idx[0])),
                    end_date=self._to_date(self.n - 1),
                    key_levels={"support": round(support, 2), "resistance": round(resistance_current, 2), "target": round(target, 2)},
                    status=PatternStatus.FORMING,
                ))

        return results

    def _detect_symmetrical_triangle(self) -> list[DetectedPattern]:
        """Converging trendlines: falling highs + rising lows."""
        results = []
        if len(self.pivot_high_idx) < 2 or len(self.pivot_low_idx) < 2:
            return results

        res_slope, _ = self._fit_trendline(self.pivot_high_idx, self.pivot_highs)
        sup_slope, _ = self._fit_trendline(self.pivot_low_idx, self.pivot_lows)

        price_range = np.max(self.high) - np.min(self.low)
        if price_range == 0:
            return results

        res_slope_norm = res_slope / price_range * self.n
        sup_slope_norm = sup_slope / price_range * self.n

        # Symmetrical: resistance falling, support rising, converging
        if res_slope_norm < -0.05 and sup_slope_norm > 0.05:
            resistance_current = float(self.pivot_highs[-1])
            support_current = float(self.pivot_lows[-1])

            converging = min(abs(res_slope_norm) + abs(sup_slope_norm), 1.0) * 40
            touches = min(len(self.pivot_high_idx) + len(self.pivot_low_idx), 8) / 8 * 40
            symmetry = max(0, 1 - abs(abs(res_slope_norm) - abs(sup_slope_norm)) / 0.2) * 20
            confidence = min(converging + touches + symmetry, 100)

            if confidence >= 40:
                results.append(DetectedPattern(
                    pattern_type=PatternType.SYMMETRICAL_TRIANGLE,
                    direction=SignalDirection.NEUTRAL,
                    confidence=round(confidence, 1),
                    start_date=self._to_date(min(self.pivot_high_idx[0], self.pivot_low_idx[0])),
                    end_date=self._to_date(self.n - 1),
                    key_levels={"resistance": round(resistance_current, 2), "support": round(support_current, 2)},
                    status=PatternStatus.FORMING,
                ))

        return results

    # ---------- Wedge Patterns ----------
    def _detect_rising_wedge(self) -> list[DetectedPattern]:
        """Both trendlines rising but converging (bearish)."""
        results = []
        if len(self.pivot_high_idx) < 2 or len(self.pivot_low_idx) < 2:
            return results

        res_slope, _ = self._fit_trendline(self.pivot_high_idx, self.pivot_highs)
        sup_slope, _ = self._fit_trendline(self.pivot_low_idx, self.pivot_lows)

        price_range = np.max(self.high) - np.min(self.low)
        if price_range == 0:
            return results

        res_slope_norm = res_slope / price_range * self.n
        sup_slope_norm = sup_slope / price_range * self.n

        # Both rising, support rising faster (converging)
        if res_slope_norm > 0.03 and sup_slope_norm > 0.03 and sup_slope_norm > res_slope_norm:
            resistance_current = float(self.pivot_highs[-1])
            support_current = float(self.pivot_lows[-1])

            both_rising = min((res_slope_norm + sup_slope_norm) / 0.2, 1.0) * 40
            converging = min((sup_slope_norm - res_slope_norm) / 0.1, 1.0) * 30
            touches = min(len(self.pivot_high_idx) + len(self.pivot_low_idx), 6) / 6 * 30
            confidence = min(both_rising + converging + touches, 100)

            if confidence >= 40:
                results.append(DetectedPattern(
                    pattern_type=PatternType.RISING_WEDGE,
                    direction=SignalDirection.BEARISH,
                    confidence=round(confidence, 1),
                    start_date=self._to_date(min(self.pivot_high_idx[0], self.pivot_low_idx[0])),
                    end_date=self._to_date(self.n - 1),
                    key_levels={"resistance": round(resistance_current, 2), "support": round(support_current, 2)},
                    status=PatternStatus.FORMING,
                ))

        return results

    def _detect_falling_wedge(self) -> list[DetectedPattern]:
        """Both trendlines falling but converging (bullish)."""
        results = []
        if len(self.pivot_high_idx) < 2 or len(self.pivot_low_idx) < 2:
            return results

        res_slope, _ = self._fit_trendline(self.pivot_high_idx, self.pivot_highs)
        sup_slope, _ = self._fit_trendline(self.pivot_low_idx, self.pivot_lows)

        price_range = np.max(self.high) - np.min(self.low)
        if price_range == 0:
            return results

        res_slope_norm = res_slope / price_range * self.n
        sup_slope_norm = sup_slope / price_range * self.n

        # Both falling, resistance falling faster (converging)
        if res_slope_norm < -0.03 and sup_slope_norm < -0.03 and res_slope_norm < sup_slope_norm:
            resistance_current = float(self.pivot_highs[-1])
            support_current = float(self.pivot_lows[-1])

            both_falling = min((abs(res_slope_norm) + abs(sup_slope_norm)) / 0.2, 1.0) * 40
            converging = min((abs(res_slope_norm) - abs(sup_slope_norm)) / 0.1, 1.0) * 30
            touches = min(len(self.pivot_high_idx) + len(self.pivot_low_idx), 6) / 6 * 30
            confidence = min(both_falling + converging + touches, 100)

            if confidence >= 40:
                results.append(DetectedPattern(
                    pattern_type=PatternType.FALLING_WEDGE,
                    direction=SignalDirection.BULLISH,
                    confidence=round(confidence, 1),
                    start_date=self._to_date(min(self.pivot_high_idx[0], self.pivot_low_idx[0])),
                    end_date=self._to_date(self.n - 1),
                    key_levels={"resistance": round(resistance_current, 2), "support": round(support_current, 2)},
                    status=PatternStatus.FORMING,
                ))

        return results

    # ---------- Pennant ----------
    def _detect_pennant(self) -> list[DetectedPattern]:
        """Small symmetrical triangle after a strong move (pole)."""
        results = []
        min_pole_bars = 5
        min_pennant_bars = 5

        for pole_start in range(0, self.n - min_pole_bars - min_pennant_bars, 5):
            for pole_end in range(pole_start + min_pole_bars, min(pole_start + 20, self.n - min_pennant_bars)):
                pole_move_pct = (self.close[pole_end] - self.close[pole_start]) / self.close[pole_start]
                if abs(pole_move_pct) < 0.05:
                    continue

                bullish = pole_move_pct > 0

                # Pennant region
                pennant_end = min(pole_end + 20, self.n - 1)
                pennant_highs = self.high[pole_end:pennant_end + 1]
                pennant_lows = self.low[pole_end:pennant_end + 1]

                if len(pennant_highs) < min_pennant_bars:
                    continue

                # Check for convergence: highs decreasing, lows increasing
                high_slope = np.polyfit(range(len(pennant_highs)), pennant_highs, 1)[0]
                low_slope = np.polyfit(range(len(pennant_lows)), pennant_lows, 1)[0]

                if high_slope >= 0 or low_slope <= 0:
                    continue

                # Pennant range should be tight relative to pole
                pennant_range = np.max(pennant_highs) - np.min(pennant_lows)
                pole_height = abs(self.close[pole_end] - self.close[pole_start])
                if pennant_range / pole_height > 0.40:
                    continue

                tightness = 1 - pennant_range / pole_height / 0.40
                pole_strength = min(abs(pole_move_pct) / 0.10, 1.0)
                confidence = min(tightness * 40 + pole_strength * 40 + 20, 100)

                if confidence < 40:
                    continue

                direction = SignalDirection.BULLISH if bullish else SignalDirection.BEARISH
                target = self.close[pennant_end] + pole_height if bullish else self.close[pennant_end] - pole_height

                results.append(DetectedPattern(
                    pattern_type=PatternType.PENNANT,
                    direction=direction,
                    confidence=round(confidence, 1),
                    start_date=self._to_date(pole_start),
                    end_date=self._to_date(pennant_end),
                    key_levels={
                        "pole_start": round(self.close[pole_start], 2),
                        "pole_end": round(self.close[pole_end], 2),
                        "target": round(target, 2),
                    },
                    status=PatternStatus.FORMING,
                ))
                break

        results.sort(key=lambda x: x.confidence, reverse=True)
        return results[:3]

    # ---------- Cup and Handle ----------
    def _detect_cup_and_handle(self) -> list[DetectedPattern]:
        """U-shaped base (cup) followed by small consolidation (handle), then breakout."""
        results = []
        if self.n < 30:
            return results

        # Look for U-shaped pattern: high -> low -> high recovery
        for cup_start in range(0, self.n - 30, 5):
            cup_start_price = self.high[cup_start]

            # Find the bottom of the cup (lowest point)
            search_end = min(cup_start + 60, self.n - 10)
            cup_region = self.low[cup_start:search_end]
            cup_bottom_local = np.argmin(cup_region)
            cup_bottom_idx = cup_start + cup_bottom_local

            if cup_bottom_local < 5 or cup_bottom_local > len(cup_region) - 5:
                continue

            cup_bottom_price = self.low[cup_bottom_idx]
            cup_depth_pct = (cup_start_price - cup_bottom_price) / cup_start_price

            if cup_depth_pct < 0.05 or cup_depth_pct > 0.50:
                continue

            # Find right side of cup: price recovering to near cup_start level
            right_side_end = min(cup_bottom_idx + (cup_bottom_local * 2), self.n - 1)
            if right_side_end <= cup_bottom_idx + 5:
                continue

            right_side_prices = self.high[cup_bottom_idx:right_side_end + 1]
            rim_recovery = np.max(right_side_prices)

            # Cup rim should recover to within 5% of start level
            if (cup_start_price - rim_recovery) / cup_start_price > 0.05:
                continue

            rim_idx = cup_bottom_idx + np.argmax(right_side_prices)

            # Handle: small consolidation after rim (optional)
            handle_end = min(rim_idx + 15, self.n - 1)
            handle_region = self.close[rim_idx:handle_end + 1]

            if len(handle_region) < 3:
                continue

            handle_drop = (rim_recovery - np.min(self.low[rim_idx:handle_end + 1])) / rim_recovery
            if handle_drop > 0.15:
                continue

            # U-shape quality: check symmetry
            left_length = cup_bottom_local
            right_length = rim_idx - cup_bottom_idx
            symmetry = 1 - abs(left_length - right_length) / max(left_length, right_length)

            depth_score = min(cup_depth_pct / 0.15, 1.0)
            confidence = min(symmetry * 35 + depth_score * 35 + 30, 100)

            if confidence < 40:
                continue

            target = rim_recovery + (rim_recovery - cup_bottom_price)

            results.append(DetectedPattern(
                pattern_type=PatternType.CUP_AND_HANDLE,
                direction=SignalDirection.BULLISH,
                confidence=round(confidence, 1),
                start_date=self._to_date(cup_start),
                end_date=self._to_date(handle_end),
                key_levels={
                    "rim": round(rim_recovery, 2),
                    "cup_bottom": round(cup_bottom_price, 2),
                    "target": round(target, 2),
                },
                status=PatternStatus.FORMING,
            ))
            break

        return results[:2]
