# ML Scoring Engine Design

**Date:** 2026-02-06
**Status:** Approved
**Author:** jdemuth17@gmail.com

---

## Overview

Replace the hand-coded weighted-average scoring in `ReportGenerationService` with an XGBoost + LSTM ensemble that learns which signal combinations predict profitable trades. The system is a new Python microservice (`MarketAnalysis.MLService`) that sits alongside the existing FastAPI analysis service.

### Goals

1. **Better signal fusion** -- learn to combine technical, fundamental, and sentiment signals more intelligently than static weighted averages
2. **Temporal awareness** -- capture how signals evolve over time, not just today's snapshot
3. **Explainability** -- SHAP-based feature importance so every rating comes with a "why"
4. **Side-by-side comparison** -- run ML scoring alongside legacy scoring before switching over

### Non-Goals

- Conversational/chat interface (not needed)
- Replacing the existing analysis pipeline (technical, fundamental, sentiment stay as-is)
- Real-time/intraday predictions (daily granularity only)

---

## Architecture

### System Context

```
                          +---------------------------+
                          |   .NET Backend (Web)      |
                          |   DailyScanService        |
                          +------+--------+-----------+
                                 |        |
                    existing     |        |  new
                                 v        v
                +----------------+    +------------------+
                | Python Service |    | ML Service       |
                | (Port 8000)    |    | (Port 8002)      |
                | - Technicals   |    | - XGBoost models |
                | - Fundamentals |    | - LSTM models    |
                | - Sentiment    |    | - Ensemble       |
                | - Market Data  |    | - Backfill       |
                +-------+--------+    +--------+---------+
                        |                      |
                        v                      v
                   +----+----------------------+----+
                   |         PostgreSQL              |
                   |  PriceHistory, TechnicalSignal, |
                   |  FundamentalSnapshot,           |
                   |  SentimentScore, ScanReport     |
                   +--------------------------------+
```

### Hardware

- **GPU:** NVIDIA RTX A4000 (16GB VRAM)
- **XGBoost training:** CPU only, ~2 minutes
- **LSTM training:** GPU, ~2-3GB VRAM, ~30 minutes
- **Inference:** Both models combined < 1GB VRAM

---

## Model Architecture

### Two Models Per Category

Four categories (DayTrade, SwingTrade, ShortTermHold, LongTermHold) each get their own pair of models -- 8 models total plus an ensemble layer.

### XGBoost (Cross-Sectional Scorer)

Answers: "How does this stock look right now vs all other stocks?"

- **Input:** 45-feature vector (single point in time)
- **Objective:** `binary:logistic` (probability of profitable trade)
- **Secondary head:** Regression on actual forward return
- **Config:** ~500 trees, max depth 6, learning rate 0.05
- **Interpretability:** SHAP values per prediction
- **Training time:** ~2 minutes on CPU

### LSTM (Temporal Predictor)

Answers: "Based on how signals have evolved over 60 days, what's the outlook?"

- **Input:** (60, 45) -- 60-day sequence of 45 features
- **Architecture:**
  - LSTM Layer 1: 128 units, dropout 0.3
  - LSTM Layer 2: 64 units, dropout 0.3
  - Dense: 32 units, ReLU
  - Output: 2 heads (sigmoid classification + linear regression)
- **Framework:** PyTorch
- **Optimizer:** AdamW, lr=1e-3, cosine annealing
- **Batch size:** 256
- **Epochs:** 50 with early stopping (patience=10)
- **Loss:** BCE (0.7 weight) + MSE (0.3 weight)
- **Training time:** ~30 minutes on GPU

### Ensemble Layer

```
final_score = (alpha * xgboost_probability) + (beta * lstm_probability)
```

- alpha and beta learned via logistic regression on validation set
- Recalibrated weekly alongside XGBoost retraining
- Final score normalized to 0-100

---

## Feature Engineering

### Feature Vector (45 features)

#### Technical Features (~20)

| Feature | Source |
|---------|--------|
| RSI(14) | TechnicalSignal / indicators |
| MACD signal line | indicators |
| MACD histogram | indicators |
| SMA(20)/SMA(50) ratio | indicators |
| SMA(50)/SMA(200) ratio | indicators |
| Bollinger Band %B | indicators |
| ADX strength | indicators |
| ATR(14) normalized by price | indicators |
| Stochastic %K, %D | indicators |
| OBV slope (5-day) | indicators |
| Volume ratio (today / 20-day avg) | PriceHistory |
| Best pattern confidence (0-100) | TechnicalSignal |
| Best pattern direction (-1/0/1) | TechnicalSignal |
| Number of active patterns | TechnicalSignal |
| Days since last pattern detected | TechnicalSignal |

#### Fundamental Features (~15)

| Feature | Source |
|---------|--------|
| P/E ratio | FundamentalSnapshot |
| Forward P/E | FundamentalSnapshot |
| PEG ratio | FundamentalSnapshot |
| Price-to-Book | FundamentalSnapshot |
| Profit margin | FundamentalSnapshot |
| Operating margin | FundamentalSnapshot |
| ROE | FundamentalSnapshot |
| Debt-to-Equity | FundamentalSnapshot |
| Free Cash Flow / Market Cap | FundamentalSnapshot |
| Revenue growth (YoY) | FundamentalSnapshot |
| Earnings growth (YoY) | FundamentalSnapshot |
| Beta | FundamentalSnapshot |
| Dividend yield | FundamentalSnapshot |
| ValueScore, QualityScore | FundamentalSnapshot |
| GrowthScore, SafetyScore | FundamentalSnapshot |

#### Sentiment Features (~10)

| Feature | Source |
|---------|--------|
| News positive/negative/neutral | SentimentScore |
| Reddit positive/negative/neutral | SentimentScore |
| StockTwits positive/negative/neutral | SentimentScore |
| Total sample size | SentimentScore |

### LSTM Sequences

- 60-day sliding window of the same 45 features
- Shape: `(60, 45)` per sample
- Z-score normalized per stock within the window

### Ground Truth Labels

| Category | Horizon | Threshold | Label |
|----------|---------|-----------|-------|
| DayTrade | 1 day | > 2% return | 1 |
| SwingTrade | 5 days | > 5% return | 1 |
| ShortTermHold | 10 days | > 8% return | 1 |
| LongTermHold | 30 days | > 15% return | 1 |

Plus regression target: actual forward return (%) for confidence ranking.

### Training Split

- **Train:** 2022-2023 (~2 years)
- **Validation:** Jan-Jun 2024
- **Test:** Jul 2024-present (never seen during training)
- Walk-forward validation to prevent look-ahead bias

---

## Backfill Pipeline

Since the Market Analysis system is still in development with no historical analysis data, a one-time backfill generates training data.

### Phase 1: Historical Price Data

- 3 years of daily OHLCV for S&P 500 + NASDAQ 100 (~600 tickers)
- ~750 trading days x 600 tickers = ~450,000 price rows
- Reuses existing `FetchPricesAsync` with `period="3y"`

### Phase 2: Retroactive Technical Signals

- For each ticker, for each trading day: run 120-day trailing window through existing technical analysis
- Calls existing Python service `/api/technicals/full-analysis`
- 600 tickers x 500 days = 300,000 analysis calls
- Batched (10 tickers/batch), resumable, estimated 8-12 hours first run

### Phase 3: Retroactive Fundamentals

- yfinance quarterly financials per ticker
- ~600 tickers x 12 quarters = 7,200 snapshots
- Forward-filled to daily granularity at training time

### Phase 4: Sentiment (Limited)

Historical sentiment data is not available for backfill. Strategy:
- Set all historical sentiment scores to 0.5 (neutral)
- Models learn to ignore low-signal features automatically
- After 2-3 months of live data collection, retrain and sentiment features begin contributing

### Phase 5: Label Generation

- For each ticker-day with complete features, compute forward returns at 1/5/10/30 day horizons
- Generate binary labels per category threshold
- Skip last 30 days (no forward labels available)

### Resulting Dataset

| Dataset | Samples | Features |
|---------|---------|----------|
| XGBoost training | ~250,000 | 45 |
| LSTM training | ~200,000 | 60 x 45 |
| Validation | ~40,000 | -- |
| Test (held out) | ~40,000 | -- |

---

## Service Structure

```
MarketAnalysis.MLService/
├── app/
│   ├── main.py                     # FastAPI entry point
│   ├── config.py                   # DB connection, model paths, hyperparams
│   ├── models/
│   │   ├── xgboost_model.py        # Train/predict/load/save
│   │   ├── lstm_model.py           # Train/predict/load/save
│   │   └── ensemble.py             # Combine predictions + calibration
│   ├── features/
│   │   ├── feature_builder.py      # Build 45-feature vectors from DB data
│   │   ├── sequence_builder.py     # Build 60-day LSTM sequences
│   │   └── normalizer.py           # Z-score normalization
│   ├── backfill/
│   │   ├── price_backfill.py       # Historical OHLCV
│   │   ├── technical_backfill.py   # Retroactive indicators/patterns
│   │   ├── fundamental_backfill.py # Quarterly fundamentals
│   │   └── label_generator.py      # Forward-return labels
│   ├── routers/
│   │   ├── predict.py              # POST /api/ml/predict
│   │   ├── train.py                # POST /api/ml/train
│   │   ├── backfill.py             # POST /api/ml/backfill
│   │   └── health.py               # GET /api/ml/health
│   └── db/
│       ├── connection.py           # SQLAlchemy async to PostgreSQL
│       └── queries.py              # Read existing analysis tables
├── trained_models/                  # Saved model artifacts
│   ├── xgboost_{category}.json     # 4 XGBoost models
│   ├── lstm_{category}.pt          # 4 LSTM models
│   └── ensemble_weights.json       # Ensemble calibration
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## API Endpoints

### Prediction

```
POST /api/ml/predict
Body: {
  "tickers": ["AAPL", "NVDA", ...],
  "categories": ["DayTrade", "SwingTrade", ...]
}
Response: {
  "predictions": [
    {
      "ticker": "AAPL",
      "category": "SwingTrade",
      "xgboost_score": 78.3,
      "lstm_score": 72.1,
      "ensemble_score": 75.5,
      "predicted_return_pct": 6.2,
      "confidence": 0.82,
      "top_features": [
        {"feature": "rsi_14", "impact": +12.3},
        {"feature": "bull_flag_confidence", "impact": +9.8},
        {"feature": "news_sentiment_positive", "impact": +5.1}
      ]
    }
  ]
}
```

### Training

```
POST /api/ml/train
Body: { "models": ["xgboost", "lstm", "ensemble"], "categories": ["all"] }
Response: { "status": "started", "job_id": "abc123" }

GET /api/ml/train/{job_id}/status
Response: { "status": "completed", "metrics": { "daytrade_auc": 0.73, ... } }
```

### Backfill

```
POST /api/ml/backfill
Body: { "start_date": "2022-01-01", "phases": ["prices", "technicals", "fundamentals", "labels"] }
Response: { "status": "started", "job_id": "xyz789" }
```

### Health

```
GET /api/ml/health
Response: {
  "status": "healthy",
  "models_loaded": ["xgboost_daytrade", "xgboost_swingtrade", ...],
  "last_trained": "2026-02-05T18:30:00Z",
  "training_samples": 250000
}
```

---

## .NET Integration

### New Client

Add `MLServiceClient` to .NET backend, same pattern as existing `PythonServiceClient`:
- Polly retry policy (3 retries, exponential backoff)
- Circuit breaker (5 failures, 30-second break)
- Base URL configurable via `appsettings.json`

### Scoring Toggle

Add `UseMlScoring` boolean to `UserScanConfig` entity:

```csharp
// In ReportGenerationService
if (config.UseMlScoring)
    scores = await _mlClient.PredictAsync(tickers, category);
else
    scores = ScoreForCategoryLegacy(tickers, category);
```

This allows side-by-side comparison before fully switching over.

### Enhanced Report Reasoning

`ScanReportEntry.Reasoning` JSON changes from static weight breakdown to:

```json
{
  "xgboost_score": 81.2,
  "lstm_score": 76.8,
  "ensemble_score": 79.3,
  "predicted_return_pct": 4.8,
  "model_confidence": 0.79,
  "top_drivers": [
    "RSI oversold (28.4) contributed +14.2 points",
    "Bull flag pattern (confidence 85%) contributed +11.7 points",
    "News sentiment shifted positive over 5 days contributed +6.3 points"
  ]
}
```

### Docker Compose Addition

```yaml
ml-service:
  build: ./src/MarketAnalysis.MLService
  ports:
    - "8002:8002"
  volumes:
    - ./trained_models:/app/trained_models
  environment:
    - DATABASE_URL=postgresql://...
    - PYTHON_SERVICE_URL=http://python-service:8000
  deploy:
    resources:
      reservations:
        devices:
          - capabilities: [gpu]
```

---

## Retraining Schedule

| Model | Frequency | Trigger | Duration |
|-------|-----------|---------|----------|
| XGBoost (4 models) | Weekly (Sunday) | Hangfire recurring job | ~2 min (CPU) |
| LSTM (4 models) | Monthly (1st Sunday) | Hangfire recurring job | ~30 min (GPU) |
| Ensemble weights | Weekly (with XGBoost) | Hangfire recurring job | ~10 sec |

---

## Implementation Roadmap

### Phase 1: Project Scaffolding & Database Access (Week 1)

- Set up FastAPI project structure
- SQLAlchemy async connection to existing PostgreSQL
- Read-only queries for PriceHistory, TechnicalSignal, FundamentalSnapshot, SentimentScore
- Health endpoint, Docker configuration
- **Deliverable:** Service starts, connects to DB, returns raw data

### Phase 2: Backfill Pipeline (Weeks 2-3)

- Price backfill: 3 years OHLCV for ~600 tickers
- Technical backfill: retroactive indicators/patterns via existing Python service
- Fundamental backfill: quarterly snapshots from yfinance
- Label generation: forward returns at 1/5/10/30 day horizons
- Resumable progress tracking
- **Deliverable:** ~250,000+ labeled training samples in PostgreSQL

### Phase 3: Feature Engineering & XGBoost (Week 4)

- Feature builder: 45-feature vectors from raw DB data
- Train 4 XGBoost models
- SHAP integration for explainability
- Evaluate on held-out test set (AUC, precision, recall)
- `/api/ml/predict` endpoint (XGBoost only)
- **Deliverable:** Working predictions, comparable against legacy scores

### Phase 4: LSTM Model (Weeks 5-6)

- Sequence builder: 60-day sliding windows with normalization
- PyTorch LSTM with dual heads
- Train 4 LSTM models
- Evaluate temporal lift over XGBoost alone
- **Deliverable:** LSTM predictions alongside XGBoost

### Phase 5: Ensemble & .NET Integration (Week 7)

- Calibrate ensemble weights on validation set
- Add `MLServiceClient` to .NET backend
- Add `UseMlScoring` toggle to `UserScanConfig`
- Wire into `DailyScanService`
- Side-by-side comparison in scan reports
- **Deliverable:** Toggle between legacy and ML scoring in UI

### Phase 6: Automation & Monitoring (Week 8)

- Hangfire jobs for weekly/monthly retraining
- Model performance tracking over time
- Drift detection alerts
- Historical backtest comparison (ML vs legacy)
- **Deliverable:** Fully automated, self-improving scoring pipeline

---

## Success Metrics

| Metric | Target | How Measured |
|--------|--------|-------------|
| DayTrade AUC | > 0.65 | Test set evaluation |
| SwingTrade AUC | > 0.65 | Test set evaluation |
| ShortTermHold AUC | > 0.60 | Test set evaluation |
| LongTermHold AUC | > 0.60 | Test set evaluation |
| ML vs Legacy lift | > 10% better precision | Side-by-side on same day's scan |
| Inference latency | < 5 sec for 600 tickers | End-to-end predict call |
| Backfill completion | 100% of ~600 tickers | Backfill status endpoint |

---

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| Overfitting to historical patterns | Walk-forward validation, no future data leakage, separate test set |
| Backfill takes too long | Resumable, batched, can run over multiple days |
| Sentiment features useless initially | Neutral defaults, models ignore low-signal features, retrain once live data accumulates |
| GPU memory pressure (FinBERT + LSTM) | Services on separate ports, never loaded simultaneously during daily scan |
| Model degrades over time | Weekly retraining, drift detection, performance tracking dashboard |
| Legacy scoring is actually better | `UseMlScoring` toggle, keep legacy code, compare continuously |
