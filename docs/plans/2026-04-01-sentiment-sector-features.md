# Sentiment Backfill Fix + Sector Momentum Features

## Overview

The ML training dataset currently has 10 sentiment columns (news/reddit/stocktwits positive/negative/neutral + sample size) stuck at 0.5 (neutral) because `label_generator.py` never queries the `SentimentScore` table during historical backfill. This means ~23% of features (10/43) provide zero signal during training, creating a train/inference distribution mismatch (runtime inference uses real sentiment). Additionally, `Stock.Sector` and `Stock.Industry` fields are populated but never used as features, missing a well-established predictive signal (sector momentum).

Approach B is implemented: batch-preload all `SentimentScore` records and all sector peer prices before the per-stock loop, compute features via in-memory lookups, and mirror the same logic in `feature_builder.py` for live inference. `ALL_FEATURES` expands from 43 → 46. A full re-backfill and retrain follows code changes.

## Planning Context

### Decision Log

| Decision | Reasoning Chain |
|---|---|
| Batch-preload sentiment before per-stock loop | Per-stock DB queries would cause N×M query fan-out (5500 stocks × many dates) → query storm → training takes 10x longer → batch-load all records once and slice in-memory |
| Batch-preload peer prices before sector momentum | Sector momentum requires prices for ALL peers on each date → per-stock live queries would be N×K×T queries → preloading all active-stock prices once and grouping by sector in pandas is orders of magnitude faster |
| Sentiment fallback = 0.5 (neutral) (user-specified) | Missing data should carry no bias → 0.5 neutral is by convention "no signal" for normalized [0,1] sentiment values → alternatives (0.0 or NaN) introduce negative signal or require special NaN handling downstream; user confirmed 0.5 as best option |
| 90-day sentiment lookback in training backfill | Runtime inference uses 7-day window because it fetches "latest available" mood → training backfill needs point-in-time accuracy to avoid future-leakage → 90-day forward-fill mirrors how fundamentals are handled (take most recent snapshot before each row date) → maximizes historical coverage without crossing into future data |
| Self-exclusion from sector average | Including a stock in its own sector average means the stock's return partially determines its own feature value → this creates indirect look-ahead: if stock had large return on day D, sector average increases, making its own sector_momentum feature appear more favourable → excluding self prevents this circular dependency and keeps the feature causally valid |
| Minimum 3 sector peers for valid momentum (user-specified) | A sector average with <3 stocks is not statistically meaningful → fewer peers means one outlier dominates the signal → 3 is the minimum to suppress gross distortion while allowing small sectors; user confirmed this threshold |
| Sector momentum = calendar 20-day rolling window | `return_Nd = (close_D / close_{D-N}) - 1` over 5/10/20 calendar days using the price DataFrame index (already sorted chronologically) → matches how all other return features are computed in the codebase |
| 300-day peer price lookback for sector momentum at inference | Deepest technical feature is SMA200/ADX requiring 200 days of history → sector peers must supply the same depth to compute their returns correctly → 300d = 200 (SMA200 minimum) + 100 days safety margin for data gaps and weekends → failure mode if insufficient: for stocks with <300 trading days (recent IPOs or data gaps) sector momentum falls back to 0.0 rather than erroring → this matches the existing `build_snapshot` lookback convention seen in `feature_builder.py` |
| NULL sector fallback = 0.0 (user-specified) | Treat NULL sector stocks as having no valid peer group → sector_momentum_* = 0.0; computing an "Unknown" pseudo-sector would mix unrelated stocks and produce noise → 0.0 is neutral and consistent with the minimum-peers fallback |
| ALL_FEATURES single source of truth in feature_builder.py | `label_generator.py` already imports `ALL_FEATURES` from `feature_builder.py` → extending the list in one place propagates to both train and inference paths automatically → prevents feature-order divergence |
| Property-based unit tests | User-specified → property tests verify invariants hold across many generated inputs rather than testing specific examples |
| Mock integration tests | User-specified → avoids DB dependency in CI, keeps tests fast |
| No e2e tests | User-specified |

### Rejected Alternatives

| Alternative | Why Rejected |
|---|---|
| Option A: sentiment only | Leaves sector momentum (known predictive signal, zero work for data) on the table → same retrain cost regardless |
| Option C: async parallelism | Adds asyncio.Semaphore/gather complexity → current sequential per-stock loop completes without hitting any timeout → premature optimization |
| Sentiment window = 7 days (match runtime) | Runtime uses 7-day window because it fetches "latest available" → training backfill needs point-in-time accuracy → a 90-day lookback window (forward-filled) mirrors how fundamentals are handled and avoids gaps |
| Sector momentum using trading days | Calendar days are simpler, consistent with existing `return_Nd` columns already in the dataset, and the difference is negligible for 5/10/20-day windows |

### Constraints & Assumptions

- `SentimentScore` table may be sparse or empty for historical dates → sentinel 0.5 fallback ensures backward compatibility
- `LSTM` and `XGBoost` models are column-order-sensitive → `ALL_FEATURES` list order must not change for existing columns; new columns appended at end
- Both `label_generator.py` and `feature_builder.py` must express identical feature computations — divergence causes silent train/inference mismatch
- Re-backfill (phase 4 labels only) must run before retraining; price/fundamental data already valid
- Existing trained models in `trained_models/` become stale (43-dim) after new 46-dim dataset — must retrain before serving predictions

### Known Risks

| Risk | Mitigation | Anchor |
|---|---|---|
| SentimentScore table empty → no improvement | Sentinel 0.5 fallback; implementation still correct and future-proof when sentiment pipeline runs | label_generator.py:~L313 |
| Sector field NULL for stocks without fundamentals | Set sector_momentum_* = 0.0 for stocks with NULL sector (< 5% expected) — confirmed in Decision Log: "NULL sector fallback (user-specified: 0.0)" | Stock.cs:L16 |
| Memory spike loading all peer prices | RTX A4000 system has 32GB RAM; all active-stock price DataFrame estimated ~2-4GB → acceptable; add `del` after computation | sequence_builder.py note |
| Feature order corruption | Append new features at end of ALL_FEATURES list; verify `len(ALL_FEATURES)==46` in test | feature_builder.py:L15-46 |
| Stale 43-dim models served post-deploy | model_registry loads models at startup; after retrain old .pt/.json files overwritten → no mix possible in single process | model_registry.py |

## Invisible Knowledge

### Architecture

```
Training Path:
  label_generator.py
    ├── phase 0: batch-load SentimentScore → {stock_id: [rows]} dict
    ├── phase 0: batch-load all prices grouped by sector → {sector: DataFrame}
    └── per-stock loop:
          _build_dataset_for_stock(stock_id, ticker, sentiment_map, sector_momentum_map)
            ├── technical features (vectorized, unchanged)
            ├── fundamental features (forward-fill, unchanged)
            ├── sentiment features   [FIXED: was hardcoded 0.5]
            └── sector momentum      [NEW: 3 columns]

Inference Path:
  feature_builder.py
    ├── build_batch_snapshots(stock_ids, as_of_date)
    │     ├── batch fetch sentiment (existing: get_batch_latest_sentiment)
    │     ├── batch fetch sector peers prices (NEW)
    │     └── compute sector_momentum per stock
    └── build_sequence(stock_id, as_of_date)
          └── per-date sector_momentum lookup (NEW)
```

### Data Flow

```
SentimentScore table
  └─ batch query ALL records for all active stocks
       └─ grouped by StockId → dict
            └─ passed to per-stock builder → forward-fill to date row

PriceHistory table (all active stocks)
  └─ loaded once, grouped by Sector
       └─ for each date D and sector S:
            avg_return = mean( (close_D / close_{D-N}) - 1  for all peers in S where !=self )
            stored as {sector: {date: (r5, r10, r20)}}
            │
            └─ joined into per-stock DataFrame → sector_momentum_5d/10d/20d columns

training_dataset.parquet (46 cols after fix)
  └─ loaded by train.py
       └─ ALL_FEATURES (46) extracted → XGBoost / LSTM / Ensemble training
```

### Why This Structure

- `label_generator.py` and `feature_builder.py` are the two codepaths that must stay in sync. The single `ALL_FEATURES` list in `feature_builder.py` (imported by `label_generator.py`) is the contract between them.
- Sector momentum must exclude self (the stock being evaluated) from the peer average to avoid look-ahead. If a stock is its own sector outlier (e.g., huge return day), including itself in the average would dilute the sector signal toward the stock's own return.

### Invariants

1. `ALL_FEATURES` list order is immutable after models are trained — changing order without retraining produces garbage XGBoost predictions.
2. Sentiment fallback is always 0.5 (not NaN, not 0.0) to maintain the [0,1] normalized range that XGBoost/LSTM expect.
3. Sector momentum is always 0.0 (not NaN) when fewer than 3 peers exist — `NaN` propagation would corrupt LSTM sequences.
4. Features computed in `label_generator.py` (training) and `feature_builder.py` (inference) must be mathematically identical for the same inputs.

### Tradeoffs

- **Batch-preload vs. lazy query**: Trading ~2-4GB RAM peak for an estimated 50-100x reduction in DB round-trips. Acceptable given 32GB system RAM.
- **Calendar days vs. trading days**: Calendar-day momentum is slightly noisier around weekends/holidays but matches the existing `return_Nd` convention in the dataset. Consistency beats marginal precision.
- **90-day sentiment lookback vs. 7-day**: 7-day window used at inference time is appropriate for "latest mood". Training backfill uses 90-day forward-fill (take most recent record before each date) to maximize data coverage during historical periods when sentiment wasn't collected daily.

---

## Milestones

### Milestone 1: Extend ALL_FEATURES and add helpers in feature_builder.py

**Files**: `src/MarketAnalysis.MLService/app/features/feature_builder.py`

**Flags**: `conformance`, `needs-rationale`

**Requirements**:
- Add `SECTOR_FEATURES = ["sector_momentum_5d", "sector_momentum_10d", "sector_momentum_20d"]` constant after `SENTIMENT_FEATURES`
- Extend `ALL_FEATURES = TECHNICAL_FEATURES + FUNDAMENTAL_FEATURES + SENTIMENT_FEATURES + SECTOR_FEATURES` (43 → 46)
- Add private method `_compute_sector_momentum_features(prices_df, sector_peer_prices_df)` that:
  - Takes a stock's price DataFrame and a concatenated DataFrame of all peer prices (same sector, excluding self)
  - For each date in the stock's price index, computes average return over 5/10/20 calendar days across peers
  - Returns 0.0 if fewer than 3 unique peer tickers have data for that window
  - Returns 0.0 if date is within first 20 rows (insufficient history)
- Add private method `_compute_sentiment_features_from_records(records: list[SentimentScore], as_of_date: date)` that mirrors the existing `_compute_sentiment_features()` but accepts a pre-fetched list instead of querying the DB — used by label_generator.py's in-memory dict

**Acceptance Criteria**:
- `len(ALL_FEATURES) == 46`
- `_compute_sector_momentum_features` with empty peer df returns all 0.0
- `_compute_sector_momentum_features` with 2 peers returns 0.0 (below threshold)
- `_compute_sector_momentum_features` with 5 peers and known returns produces correct average

**Tests**:
- **Test file**: `src/MarketAnalysis.MLService/tests/test_feature_builder.py` (create if not exists)
- **Type**: property-based (user-specified)
- **Backing**: user-specified
- **Scenarios**:
  - Property: for any N peer stocks with uniform returns R, sector_momentum == R
  - Property: for <3 peers, always returns 0.0 regardless of input
  - Edge: single-stock sector → 0.0
  - Edge: all-NaN peer prices → 0.0

**Code Intent**:
- Add `SECTOR_FEATURES` list constant after `SENTIMENT_FEATURES`
- Update `ALL_FEATURES` concatenation to include `SECTOR_FEATURES`
- Add `_compute_sector_momentum_features(self, stock_prices_df, peer_prices_df)` as instance method on `FeatureBuilder` class — takes two DataFrames indexed by date, returns a dict `{date: (r5, r10, r20)}` — uses pandas vectorized `.shift(N)` on peer prices to compute N-day returns, then `.mean(axis=1)` across tickers
- Add `_compute_sentiment_from_records(records)` static method that accepts a list of `SentimentScore` ORM objects (already fetched) and returns a dict of the 10 sentiment feature values — refactors the existing inline logic in `_compute_sentiment_features()`

**Code Changes**:

```diff
--- a/src/MarketAnalysis.MLService/app/features/feature_builder.py
+++ b/src/MarketAnalysis.MLService/app/features/feature_builder.py
@@ -63,10 +63,16 @@ SENTIMENT_FEATURES = [
     "sentiment_sample_size",
 ]
 
+SECTOR_FEATURES = [
+    "sector_momentum_5d",
+    "sector_momentum_10d",
+    "sector_momentum_20d",
+]
+
 # Not included in total but used for labels
 LABEL_COLUMNS = [
     "label_daytrade",       # 1-day return > 2%
-ALL_FEATURES = TECHNICAL_FEATURES + FUNDAMENTAL_FEATURES + SENTIMENT_FEATURES
+ALL_FEATURES = TECHNICAL_FEATURES + FUNDAMENTAL_FEATURES + SENTIMENT_FEATURES + SECTOR_FEATURES
 
 
 class FeatureBuilder:
@@ -443,6 +449,55 @@ class FeatureBuilder:
         features["sentiment_sample_size"] = float(total_samples)
         return features
 
+    @staticmethod
+    def _compute_sentiment_from_records(records: list) -> dict:
+        """
+        Extract sentiment features from pre-fetched SentimentScore records.
+        Used by label_generator for in-memory processing.
+        """
+        features = {
+            "news_positive": 0.5,
+            "news_negative": 0.5,
+            "news_neutral": 0.5,
+            "reddit_positive": 0.5,
+            "reddit_negative": 0.5,
+            "reddit_neutral": 0.5,
+            "stocktwits_positive": 0.5,
+            "stocktwits_negative": 0.5,
+            "stocktwits_neutral": 0.5,
+            "sentiment_sample_size": 0.0,
+        }
+
+        if not records:
+            return features
+
+        total_samples = 0
+        for s in records:
+            source = s.Source.lower() if s.Source else ""
+            if source == "news":
+                prefix = "news"
+            elif source == "reddit":
+                prefix = "reddit"
+            elif source == "stocktwits":
+                prefix = "stocktwits"
+            else:
+                continue
+
+            features[f"{prefix}_positive"] = float(s.PositiveScore)
+            features[f"{prefix}_negative"] = float(s.NegativeScore)
+            features[f"{prefix}_neutral"] = float(s.NeutralScore)
+            total_samples += s.SampleSize
+
+        features["sentiment_sample_size"] = float(total_samples)
+        return features
+
+    def _compute_sector_momentum_features(
+        self, stock_prices_df: pd.DataFrame, peer_prices_df: pd.DataFrame
+    ) -> dict:
+        """
+        Compute sector momentum features for each date in stock_prices_df.
+        peer_prices_df: pivoted DataFrame with columns=ticker, index=date, values=close
+        Returns dict {date: {"sector_momentum_5d": float, ...}}
+        """
+        if peer_prices_df.empty or len(peer_prices_df.columns) < 3:
+            # Fewer than 3 peers → all zeros
+            return {
+                d: {"sector_momentum_5d": 0.0, "sector_momentum_10d": 0.0, "sector_momentum_20d": 0.0}
+                for d in stock_prices_df["date"]
+            }
+
+        # Compute N-day returns for each peer ticker
+        returns_5d = (peer_prices_df / peer_prices_df.shift(5)) - 1
+        returns_10d = (peer_prices_df / peer_prices_df.shift(10)) - 1
+        returns_20d = (peer_prices_df / peer_prices_df.shift(20)) - 1
+
+        # Average across peers (axis=1 = columns)
+        avg_5d = returns_5d.mean(axis=1, skipna=True)
+        avg_10d = returns_10d.mean(axis=1, skipna=True)
+        avg_20d = returns_20d.mean(axis=1, skipna=True)
+
+        # Build result dict
+        result = {}
+        for date_val in stock_prices_df["date"]:
+            if date_val in avg_5d.index:
+                result[date_val] = {
+                    "sector_momentum_5d": float(avg_5d.loc[date_val]) if pd.notna(avg_5d.loc[date_val]) else 0.0,
+                    "sector_momentum_10d": float(avg_10d.loc[date_val]) if pd.notna(avg_10d.loc[date_val]) else 0.0,
+                    "sector_momentum_20d": float(avg_20d.loc[date_val]) if pd.notna(avg_20d.loc[date_val]) else 0.0,
+                }
+            else:
+                result[date_val] = {"sector_momentum_5d": 0.0, "sector_momentum_10d": 0.0, "sector_momentum_20d": 0.0}
+
+        return result
+
     @staticmethod
     def _safe_float(value, default: float = 0.0) -> float:
         if value is None:
```

---

### Milestone 2: Fix sentiment backfill in label_generator.py

**Files**: `src/MarketAnalysis.MLService/app/backfill/label_generator.py`

**Flags**: `conformance`, `needs-rationale`, `performance`

**Requirements**:
- Before the per-stock loop in `run_label_generation()`, batch-load ALL `SentimentScore` records for all active stock IDs:
  - Single query: `SELECT * FROM SentimentScores WHERE StockId IN (...all active ids...)`
  - Group into `sentiment_map: dict[int, list[SentimentScore]]` keyed by `StockId`
- Modify `_build_dataset_for_stock()` signature to accept `sentiment_records: list[SentimentScore]` parameter
- Replace the hardcoded `df[col] = 0.5` block with real sentiment lookup:
  - Build `{date: {source: SentimentScore}}` from `sentiment_records`
  - For each row date in price DataFrame, find most recent SentimentScore from any source within the past 90 days
  - Populate source-specific columns (news_*, reddit_*, stocktwits_*) from matching record, 0.5 fallback if none
  - `sentiment_sample_size` = sum of `SampleSize` across all sources for that date window

**Acceptance Criteria**:
- For a stock that has SentimentScore records in the DB, the exported parquet has non-0.5 values in sentiment columns
- For a stock with no SentimentScore records, all sentiment columns remain 0.5
- No additional DB queries per stock after batch-load (verify via mock counting)

**Tests**:
- **Test file**: `src/MarketAnalysis.MLService/tests/test_label_generator.py` (create if not exists)
- **Type**: property-based + mock integration (user-specified)
- **Backing**: user-specified
- **Scenarios**:
  - Mock: SentimentScore map with data → sentiment columns populated
  - Mock: empty SentimentScore map → all columns 0.5
  - Property: sentiment values always in [0, 1] range regardless of input
  - Mock: multiple sources for same date → each source's columns populated independently

**Code Intent**:
- In `run_label_generation()`: after fetching all active stocks, run one batch DB query to fetch all `SentimentScore` rows for all active stock IDs; group into `{stock_id: list[SentimentScore]}` dict
- Pass the per-stock slice as new `sentiment_records` parameter to `_build_dataset_for_stock()`
- In `_build_dataset_for_stock()`: replace the hardcoded 0.5 initialization block with a call to the new `FeatureBuilder._compute_sentiment_from_records()` helper (M1), passing the stock's sentiment records and the row's date
- Handle missing records gracefully (empty list → 0.5 defaults)

**Code Changes**:

```diff
--- a/src/MarketAnalysis.MLService/app/backfill/label_generator.py
+++ b/src/MarketAnalysis.MLService/app/backfill/label_generator.py
@@ -102,7 +102,8 @@ def _compute_vectorized_technical_features(prices_df: pd.DataFrame) -> pd.DataF
 
 
 async def _build_dataset_for_stock(
     stock_id: int,
     ticker: str,
+    sentiment_records: list,
 ) -> pd.DataFrame | None:
     """Build complete feature + label DataFrame for one stock."""
@@ -254,9 +255,33 @@ async def _build_dataset_for_stock(
                 df.at[idx, "safety_score"] = (float(f.SafetyScore) / 100.0) if f.SafetyScore else 0.5
 
     # Add sentiment features (default neutral 0.5)
-    for col in SENTIMENT_FEATURES:
-        if "sample_size" in col:
-            df[col] = 0.0
-        else:
-            df[col] = 0.5
+    # Build lookup: date -> list of SentimentScore records within 90-day window
+    sentiment_by_date = {}
+    for s in sentiment_records:
+        sentiment_by_date.setdefault(s.AnalysisDate, []).append(s)
+
+    # Initialize columns
+    for col in SENTIMENT_FEATURES:
+        if "sample_size" in col:
+            df[col] = 0.0
+        else:
+            df[col] = 0.5
+
+    # For each row, look back 90 days for most recent sentiment
+    for idx, row in df.iterrows():
+        row_date = row["date"]
+        lookback_start = row_date - timedelta(days=90)
+
+        # Find most recent sentiment records in window
+        recent_records = []
+        for sd in sorted(sentiment_by_date.keys(), reverse=True):
+            if lookback_start <= sd <= row_date:
+                recent_records.extend(sentiment_by_date[sd])
+                break  # Take most recent date only
+
+        if recent_records:
+            sent_features = FeatureBuilder._compute_sentiment_from_records(recent_records)
+            for col, val in sent_features.items():
+                df.at[idx, col] = val
 
-    # Sentiment is not available for historical backfill — stays at neutral defaults
 
     # Add metadata
@@ -306,12 +331,28 @@ async def run_label_generation():
 
     async with async_session() as session:
         stocks = await get_active_stocks(session)
+
+        # Batch-load all sentiment records for all active stocks
+        stock_ids = [s.Id for s in stocks]
+        logger.info(f"Batch-loading sentiment records for {len(stock_ids)} stocks")
+        
+        result = await session.execute(
+            select(SentimentScore)
+            .where(SentimentScore.StockId.in_(stock_ids))
+            .order_by(SentimentScore.StockId, SentimentScore.AnalysisDate)
+        )
+        all_sentiment_records = result.scalars().all()
+        
+        # Group by StockId
+        sentiment_map: dict[int, list] = {sid: [] for sid in stock_ids}
+        for rec in all_sentiment_records:
+            sentiment_map[rec.StockId].append(rec)
+        
+        logger.info(f"Loaded {len(all_sentiment_records)} sentiment records")
 
     logger.info(f"Building training data for {len(stocks)} stocks")
 
@@ -321,7 +362,7 @@ async def run_label_generation():
 
     for idx, stock in enumerate(stocks):
         try:
-            df = await _build_dataset_for_stock(stock.Id, stock.Ticker)
+            df = await _build_dataset_for_stock(stock.Id, stock.Ticker, sentiment_map[stock.Id])
             if df is not None and len(df) > 0:
                 all_frames.append(df)
                 processed += 1
```

---

### Milestone 3: Add sector momentum backfill in label_generator.py

**Files**: `src/MarketAnalysis.MLService/app/backfill/label_generator.py`

**Flags**: `conformance`, `performance`, `complex-algorithm`, `needs-rationale`

**Requirements**:
- Before the per-stock loop in `run_label_generation()`, build a sector momentum lookup:
  1. Query `Stock` table for all active stocks' `Sector` field
  2. Query `PriceHistory` for close prices of ALL active stocks (full date range)
  3. For each unique sector, build a pivoted DataFrame: rows=dates, cols=tickers, values=close price
  4. Compute returns per ticker: `ret_Nd = (close / close.shift(N)) - 1` for N=5,10,20
  5. For each date and sector, compute mean across tickers (excluding self when used per-stock)
  6. Store as `sector_momentum_map: dict[str, DataFrame]` where DataFrame has columns `[momentum_5d, momentum_10d, momentum_20d]` indexed by date
- Modify `_build_dataset_for_stock()` to accept `ticker`, `sector`, `sector_momentum_map` parameters
- Inside `_build_dataset_for_stock()`:
  - Look up `sector_momentum_map[sector]` for this stock's sector
  - For each date in price DataFrame, join sector momentum values (excluding self ticker's contribution)
  - Assign to `sector_momentum_5d`, `sector_momentum_10d`, `sector_momentum_20d` columns
  - Use 0.0 if sector has <3 peers OR date is not in sector momentum index

**Acceptance Criteria**:
- Parquet has `sector_momentum_5d`, `sector_momentum_10d`, `sector_momentum_20d` columns
- Values for a stock with ≥3 sector peers are non-zero on most dates
- Stock with NULL sector gets 0.0 on all dates
- Stock is excluded from its own sector average (self-exclusion)

**Tests**:
- **Test file**: `src/MarketAnalysis.MLService/tests/test_label_generator.py`
- **Type**: property-based + mock integration
- **Backing**: user-specified
- **Scenarios**:
  - Mock: 5-stock sector with uniform 1% daily returns → sector_momentum_5d ≈ 0.051 (compounded)
  - Mock: 2-stock sector → all sector momentum = 0.0
  - Mock: NULL sector stock → 0.0
  - Property: sector momentum values always in [-1, 10] range (no explosions)

**Code Intent**:
- New helper `_precompute_sector_momentum(session, all_stocks)` async function in label_generator.py:
  - Queries all PriceHistory close prices for active stocks in a single JOIN query
  - Builds per-sector pivoted DataFrames
  - Returns `{sector: {ticker_self: DataFrame(columns=[5d,10d,20d], index=date)}}` — pre-excludes self for each ticker
- In `run_label_generation()`: call `_precompute_sector_momentum()` after fetching stocks, before per-stock loop
- Pass per-stock sector momentum DataFrame to `_build_dataset_for_stock()`
- In `_build_dataset_for_stock()`: merge sector momentum onto price DataFrame by date, fill missing with 0.0

**Code Changes**:

```diff
--- a/src/MarketAnalysis.MLService/app/backfill/label_generator.py
+++ b/src/MarketAnalysis.MLService/app/backfill/label_generator.py
@@ -102,10 +102,88 @@ def _compute_vectorized_technical_features(prices_df: pd.DataFrame) -> pd.DataF
     return df
 
 
+async def _precompute_sector_momentum(
+    session,
+    stocks: list[Stock],
+) -> dict[str, dict[str, pd.DataFrame]]:
+    """
+    Precompute sector momentum for all stocks.
+    Returns {sector: {ticker: DataFrame(index=date, columns=[sector_momentum_5d/10d/20d])}}
+    Each ticker's DataFrame excludes itself from sector average.
+    """
+    logger.info("Precomputing sector momentum for all stocks")
+
+    # Build stock_id -> (ticker, sector) mapping
+    stock_map = {s.Id: (s.Ticker, s.Sector) for s in stocks}
+    stock_ids = list(stock_map.keys())
+
+    # Batch-load all prices
+    result = await session.execute(
+        select(PriceHistory.StockId, PriceHistory.Date, PriceHistory.Close)
+        .where(PriceHistory.StockId.in_(stock_ids))
+        .order_by(PriceHistory.StockId, PriceHistory.Date)
+    )
+    all_prices = result.all()
+    logger.info(f"Loaded {len(all_prices)} price rows for sector momentum")
+
+    # Build DataFrame: rows=date, cols=ticker, values=close
+    price_records = []
+    for stock_id, date_val, close_val in all_prices:
+        ticker, sector = stock_map.get(stock_id, (None, None))
+        if ticker and sector:
+            price_records.append({
+                "date": date_val,
+                "ticker": ticker,
+                "sector": sector,
+                "close": float(close_val),
+            })
+
+    if not price_records:
+        return {}
+
+    all_df = pd.DataFrame(price_records)
+
+    # Group by sector
+    sectors = all_df["sector"].dropna().unique()
+    sector_momentum_map = {}
+
+    for sector in sectors:
+        sector_df = all_df[all_df["sector"] == sector]
+        tickers = sector_df["ticker"].unique()
+
+        if len(tickers) < 3:
+            # Not enough peers for this sector → skip
+            continue
+
+        # Pivot: rows=date, cols=ticker, values=close
+        pivot = sector_df.pivot(index="date", columns="ticker", values="close")
+        pivot = pivot.sort_index()
+
+        # For each ticker, compute sector momentum excluding self
+        sector_momentum_map[sector] = {}
+        for ticker in tickers:
+            # Exclude self
+            peer_tickers = [t for t in tickers if t != ticker]
+            if len(peer_tickers) < 3:
+                # After excluding self, fewer than 3 peers → all zeros
+                sector_momentum_map[sector][ticker] = pd.DataFrame({
+                    "sector_momentum_5d": 0.0,
+                    "sector_momentum_10d": 0.0,
+                    "sector_momentum_20d": 0.0,
+                }, index=pivot.index)
+            else:
+                peer_prices = pivot[peer_tickers]
+                ret_5d = (peer_prices / peer_prices.shift(5) - 1).mean(axis=1)
+                ret_10d = (peer_prices / peer_prices.shift(10) - 1).mean(axis=1)
+                ret_20d = (peer_prices / peer_prices.shift(20) - 1).mean(axis=1)
+                sector_momentum_map[sector][ticker] = pd.DataFrame({
+                    "sector_momentum_5d": ret_5d.fillna(0.0),
+                    "sector_momentum_10d": ret_10d.fillna(0.0),
+                    "sector_momentum_20d": ret_20d.fillna(0.0),
+                })
+
+    logger.info(f"Sector momentum precomputed for {len(sector_momentum_map)} sectors")
+    return sector_momentum_map
+
+
 async def _build_dataset_for_stock(
     stock_id: int,
     ticker: str,
     sentiment_records: list,
+    sector: str | None,
+    sector_momentum_map: dict,
 ) -> pd.DataFrame | None:
     """Build complete feature + label DataFrame for one stock."""
@@ -281,6 +359,18 @@ async def _build_dataset_for_stock(
             for col, val in sent_features.items():
                 df.at[idx, col] = val
 
+    # Add sector momentum features
+    if sector and sector in sector_momentum_map and ticker in sector_momentum_map[sector]:
+        momentum_df = sector_momentum_map[sector][ticker]
+        # Merge by date
+        df = df.merge(momentum_df, left_on="date", right_index=True, how="left")
+        df["sector_momentum_5d"] = df["sector_momentum_5d"].fillna(0.0)
+        df["sector_momentum_10d"] = df["sector_momentum_10d"].fillna(0.0)
+        df["sector_momentum_20d"] = df["sector_momentum_20d"].fillna(0.0)
+    else:
+        df["sector_momentum_5d"] = 0.0
+        df["sector_momentum_10d"] = 0.0
+        df["sector_momentum_20d"] = 0.0
 
     # Add metadata
     df["stock_id"] = stock_id
@@ -349,6 +439,10 @@ async def run_label_generation():
         
         logger.info(f"Loaded {len(all_sentiment_records)} sentiment records")
 
+        # Precompute sector momentum
+        sector_momentum_map = await _precompute_sector_momentum(session, stocks)
+        logger.info("Sector momentum precomputation complete")
+
     logger.info(f"Building training data for {len(stocks)} stocks")
 
     all_frames = []
@@ -357,7 +451,12 @@ async def run_label_generation():
 
     for idx, stock in enumerate(stocks):
         try:
-            df = await _build_dataset_for_stock(stock.Id, stock.Ticker, sentiment_map[stock.Id])
+            df = await _build_dataset_for_stock(
+                stock.Id,
+                stock.Ticker,
+                sentiment_map[stock.Id],
+                stock.Sector,
+                sector_momentum_map,
+            )
             if df is not None and len(df) > 0:
                 all_frames.append(df)
                 processed += 1
```

---

### Milestone 4: Add sector momentum to runtime inference in feature_builder.py

**Files**: `src/MarketAnalysis.MLService/app/features/feature_builder.py`

**Flags**: `conformance`, `performance`

**Requirements**:
- In `build_batch_snapshots(stock_ids, as_of_date)`:
  - After existing price/technical/fundamental/sentiment fetches, fetch prices for all sector peers (all stocks sharing same sector, up to `as_of_date - 300d`)
  - Compute sector momentum for each stock at `as_of_date` using the same formula as training
  - Include `sector_momentum_5d`, `sector_momentum_10d`, `sector_momentum_20d` in the returned feature dict
- In `build_snapshot(stock_id, as_of_date)`:
  - Delegate to the batch path or implement equivalent single-stock sector lookup
- In `build_sequence(stock_id, as_of_date)`:
  - For each date in the sequence window, compute sector momentum using peer prices in that window
  - Assign to feature columns in sequence DataFrame

**Acceptance Criteria**:
- `build_batch_snapshots()` returns dicts containing `sector_momentum_5d`, `sector_momentum_10d`, `sector_momentum_20d`
- Values are 0.0 (not NaN) for stocks with NULL sector or <3 peers
- No extra DB queries per stock beyond single batch peer-price fetch

**Tests**:
- **Test file**: `src/MarketAnalysis.MLService/tests/test_feature_builder.py`
- **Type**: mock integration (user-specified)
- **Backing**: user-specified
- **Scenarios**:
  - Mock: stock with 4 peers in sector → non-zero momentum
  - Mock: stock with NULL sector → 0.0 all three columns
  - Mock: stock with 2 peers → 0.0 all three columns

**Code Intent**:
- Add `_fetch_sector_peer_prices(stock_ids, sectors, as_of_date, session)` async method that batches price queries for all unique sector peers
- In `build_batch_snapshots()`: after existing bulk queries, call `_fetch_sector_peer_prices()` using already-known sector values from Stock records; call `_compute_sector_momentum_features()` (M1 helper) per stock
- In `build_sequence()`: reuse the same peer price fetch, iterate over dated windows to produce per-date sector momentum

**Code Changes**:

```diff
--- a/src/MarketAnalysis.MLService/app/features/feature_builder.py
+++ b/src/MarketAnalysis.MLService/app/features/feature_builder.py
@@ -101,6 +101,13 @@ class FeatureBuilder:
             self.session, stock_ids, as_of_date=as_of_date
         )
 
+        # Fetch stocks to get sector information
+        stock_result = await self.session.execute(
+            select(Stock).where(Stock.Id.in_(stock_ids))
+        )
+        stock_records = {s.Id: s for s in stock_result.scalars().all()}
+
+        # Fetch sector peer prices
+        sector_peers = await self._fetch_sector_peer_prices(stock_records, as_of_date)
+
         # 2. Process each stock
         results: dict[int, pd.DataFrame] = {}
@@ -121,6 +128,13 @@ class FeatureBuilder:
             features.update(self._compute_pattern_features(batch_signals.get(sid, []), as_of_date))
             features.update(self._compute_fundamental_features(batch_fundamentals.get(sid), prices_df))
             features.update(self._compute_sentiment_features(batch_sentiments.get(sid, [])))
+
+            # Sector momentum
+            stock = stock_records.get(sid)
+            if stock and stock.Sector and stock.Sector in sector_peers:
+                peer_df = sector_peers[stock.Sector].get(stock.Ticker)
+                if peer_df is not None and not peer_df.empty:
+                    momentum = self._compute_sector_momentum_features(prices_df, peer_df)
+                    latest_date = prices_df["date"].iloc[-1]
+                    features.update(momentum.get(latest_date, {"sector_momentum_5d": 0.0, "sector_momentum_10d": 0.0, "sector_momentum_20d": 0.0}))
 
             # Build 1-row DataFrame
@@ -230,6 +244,82 @@ class FeatureBuilder:
 
         return df
 
+    async def _fetch_sector_peer_prices(
+        self,
+        stock_records: dict[int, Stock],
+        as_of_date: date,
+    ) -> dict[str, dict[str, pd.DataFrame]]:
+        """
+        Fetch prices for all sector peers (excluding self) for sector momentum.
+        Returns: {sector: {ticker: peer_prices_df}}
+        peer_prices_df has columns=peer_ticker, index=date, values=close (excluding self ticker)
+        """
+        # Group stocks by sector
+        sector_tickers: dict[str, list[tuple[int, str]]] = {}
+        for sid, stock in stock_records.items():
+            if stock.Sector:
+                sector_tickers.setdefault(stock.Sector, []).append((sid, stock.Ticker))
+
+        # Fetch prices for all stocks in each sector
+        price_start = as_of_date - timedelta(days=300)
+        all_stock_ids = list(stock_records.keys())
+
+        batch_prices = await queries.get_batch_price_history(
+            self.session, all_stock_ids, start_date=price_start, end_date=as_of_date
+        )
+
+        # Build per-sector peer DataFrames
+        result = {}
+        for sector, stock_list in sector_tickers.items():
+            if len(stock_list) < 3:
+                # Not enough peers
+                continue
+
+            # Build pivoted DataFrame for this sector
+            sector_price_records = []
+            for sid, ticker in stock_list:
+                prices = batch_prices.get(sid, [])
+                for p in prices:
+                    sector_price_records.append({
+                        "date": p.Date,
+                        "ticker": ticker,
+                        "close": float(p.Close),
+                    })
+
+            if not sector_price_records:
+                continue
+
+            sector_df = pd.DataFrame(sector_price_records)
+            pivot = sector_df.pivot(index="date", columns="ticker", values="close")
+            pivot = pivot.sort_index()
+
+            # For each ticker in sector, exclude self and create peer_df
+            result[sector] = {}
+            for sid, ticker in stock_list:
+                peer_tickers = [t for _, t in stock_list if t != ticker]
+                if len(peer_tickers) < 3:
+                    result[sector][ticker] = pd.DataFrame()
+                else:
+                    result[sector][ticker] = pivot[peer_tickers]
+
+        return result
+
     def _compute_technical_indicators(self, prices: pd.DataFrame) -> dict:
         """Compute technical indicators from OHLCV DataFrame using pandas-ta."""
         features = {}
@@ -527,6 +617,10 @@ class FeatureBuilder:
             return default
```

```diff
--- a/src/MarketAnalysis.MLService/app/features/feature_builder.py
+++ b/src/MarketAnalysis.MLService/app/features/feature_builder.py
@@ -3,6 +3,7 @@ Builds 45-feature vectors from raw database data for XGBoost (snapshot)
 and 60-day sequences for LSTM (temporal).
 """
 import logging
+from sqlalchemy import select
 from datetime import date, timedelta
 from typing import Optional
 
@@ -14,6 +15,7 @@ from sqlalchemy.ext.asyncio import AsyncSession
 
 from app.config import settings
 from app.db import queries
+from app.db.models import Stock
 
 logger = logging.getLogger(__name__)
```

---

### Milestone 5: Tests

**Files**:
- `src/MarketAnalysis.MLService/tests/test_feature_builder.py`
- `src/MarketAnalysis.MLService/tests/test_label_generator.py`

**Requirements**:
- Property-based tests using `hypothesis` library
- Mock integration tests using `pytest-asyncio` + `unittest.mock`
- All tests runnable with `pytest` from `src/MarketAnalysis.MLService/`

**Acceptance Criteria**:
- `pytest tests/test_feature_builder.py` exits 0
- `pytest tests/test_label_generator.py` exits 0
- Property tests cover value ranges and invariants (not just happy paths)

**Code Intent**:
- `test_feature_builder.py`: property-based tests for `_compute_sector_momentum_features()` and `_compute_sentiment_from_records()` using `hypothesis` `st.floats()` and `st.lists()`
- `test_label_generator.py`: mock integration tests using `AsyncMock` for DB session, feeding known `SentimentScore` and price data, asserting parquet output column values

---

### Milestone 6: Documentation

**Delegated to**: @agent-technical-writer (mode: post-implementation)

**Source**: `## Invisible Knowledge` section of this plan

**Files**:
- `src/MarketAnalysis.MLService/app/features/README.md` (new)
- `src/MarketAnalysis.MLService/app/backfill/README.md` (new)
