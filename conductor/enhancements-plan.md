# Market Analysis Enhancements & Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix critical enum parsing and progress tracking bugs, optimize ML scoring performance, and unify technical analysis logic across the system.

**Architecture:** 
- Fix the .NET backend's ability to ingest Python-generated signals by handling `snake_case` to `PascalCase` conversion.
- Optimize the MLService by batching database queries for feature building.
- Improve the Python analysis accuracy by using ATR-based relative thresholds for pattern detection.
- Unify technical indicator computation to ensure consistency between charts and ML models.

**Tech Stack:** .NET 8, ASP.NET Core, FastAPI, SQLAlchemy (Async), yfinance, pandas-ta.

---

### Task 1: Fix .NET Enum Parsing Bug

The Python service returns patterns in `snake_case` (e.g., `double_top`), but the C# enum `PatternType` is in `PascalCase`. The current `Enum.TryParse` fails for these.

**Files:**
- Modify: `src/MarketAnalysis.Infrastructure/Services/MarketDataIngestionService.cs`

- [ ] **Step 1: Create a helper method for PascalCase conversion**
      Add a private method to `MarketDataIngestionService.cs` (or a shared utility) that converts `snake_case` to `PascalCase`.

- [ ] **Step 2: Update `IngestTechnicalsAsync` to use the helper**
      Update the `Enum.TryParse` call to use the converted string.

- [ ] **Step 3: Verification**
      Manually trigger a scan and verify in the logs/database that `DoubleTop` signals are successfully saved.

---

### Task 2: Fix Progress Tracker Resetting

`DailyScanService.RunFullScanAsync` calls `_progress.Start()` twice, which resets the "started" timestamp and ticker count.

**Files:**
- Modify: `src/MarketAnalysis.Infrastructure/Services/DailyScanService.cs`

- [ ] **Step 1: Remove the second `_progress.Start()` call**
      In `RunFullScanAsync`, after `PreFilterTickersAsync`, do not call `_progress.Start()` again.

- [ ] **Step 2: Update `_progress.TotalTickers` dynamically**
      Instead of re-starting, add a method to `IScanProgressTracker` or simply update the property if it's mutable to reflect the new filtered ticker count.

---

### Task 3: Optimize ML Scoring Performance

Batch database queries in `MLService/app/routers/predict.py` and `FeatureBuilder.py` to avoid N*4 database roundtrips.

**Files:**
- Modify: `src/MarketAnalysis.MLService/app/features/feature_builder.py`
- Modify: `src/MarketAnalysis.MLService/app/routers/predict.py`

- [ ] **Step 1: Implement bulk feature building**
      Add `build_batch_snapshots` to `FeatureBuilder` that takes a list of stock IDs and fetches prices, signals, and fundamentals in bulk queries.

- [ ] **Step 2: Update the `/predict` endpoint**
      Refactor the loop in `predict.py` to use the new bulk feature builder.

---

### Task 4: Async Batching in .NET Ingestion

Use `Task.WhenAll` to improve throughput of price and fundamental ingestion batches.

**Files:**
- Modify: `src/MarketAnalysis.Infrastructure/Services/MarketDataIngestionService.cs`

- [ ] **Step 1: Refactor `IngestPriceBatchesAsync`**
      Create a list of Tasks and use `Task.WhenAll` to process multiple batches concurrently (within limits).

- [ ] **Step 2: Refactor `IngestFundamentalsAsync`**
      Apply similar parallelization to the fundamentals fetch loop.

---

### Task 5: Unify Technical Indicators

Ensure `FeatureBuilder.py` and `indicator_engine.py` use the same logic (preferably `pandas-ta`).

**Files:**
- Modify: `src/MarketAnalysis.MLService/app/features/feature_builder.py`

- [ ] **Step 1: Replace manual NumPy/Pandas math**
      Import and use `pandas-ta` (or the `IndicatorEngine`) within `FeatureBuilder` to compute the technical features.

---

### Task 6: ATR-Based Pattern Detection

Modify `PatternDetector.py` to use ATR-based relative thresholds for more accurate detection across different price/volatility regimes.

**Files:**
- Modify: `src/MarketAnalysis.PythonService/services/pattern_detector.py`

- [ ] **Step 1: Compute ATR in `PatternDetector.__init__`**
      Add ATR calculation using `pandas-ta` to the constructor.

- [ ] **Step 2: Update pattern detectors**
      Modify `_detect_double_top`, `_detect_head_and_shoulders`, etc., to use `current_atr * factor` instead of hardcoded 2-3% percentages for price tolerances.

---

### Task 7: Verification & Final Testing

- [ ] **Step 1: Run full scan pipeline**
      Verify end-to-end flow.
- [ ] **Step 2: Verify ML scores**
      Ensure ML service is significantly faster and returning accurate scores.
- [ ] **Step 3: Verify pattern detection quality**
      Visually inspect a few charts to see if ATR-based detection is superior.
