# Market Analysis Daily Scanner — Implementation Plan

## Architecture Summary

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | Blazor Server (.NET 8) + MudBlazor + ApexCharts.Blazor | Dashboard, config UI, candlestick charts |
| Backend | ASP.NET Core 8 Web API + Hangfire | Orchestration, scheduling, report generation |
| Data Service | Python FastAPI | Yahoo Finance data, technicals, patterns, sentiment |
| Database | PostgreSQL + EF Core | Persistent storage for all data & reports |
| Sentiment ML | FinBERT (HuggingFace transformers) | Financial text sentiment scoring |
| Data Sources | Yahoo Finance, Finnhub, Reddit, StockTwits | Price data, fundamentals, news, social sentiment |

```
┌──────────────────────────────────────┐
│       Blazor Server Frontend         │
│   MudBlazor + ApexCharts.Blazor      │
│   Dashboard · Config · Charts        │
└──────────────┬───────────────────────┘
               │ (same process)
┌──────────────▼───────────────────────┐
│       .NET 8 Backend (Host)          │
│   API Controllers · Hangfire Jobs    │
│   Report Engine · EF Core Repos      │
└──────────┬────────────┬──────────────┘
           │ HTTP       │ EF Core
┌──────────▼──────┐ ┌───▼──────────────┐
│  Python FastAPI │ │   PostgreSQL     │
│  yfinance       │ │   Price History  │
│  pandas-ta      │ │   Fundamentals   │
│  Pattern Detect │ │   Signals/Scores │
│  FinBERT        │ │   Reports/Config │
└─────────────────┘ └──────────────────┘
```

---

## Phase 0 — Project Scaffolding & Dev Environment

**Goal:** Solution structure created, all projects buildable, dev dependencies installed.

### Step 0.1 — .NET Solution & Projects
- [ ] Create `MarketAnalysis.sln` at workspace root
- [ ] Create `src/MarketAnalysis.Web` — Blazor Server project (.NET 8)
- [ ] Create `src/MarketAnalysis.Core` — Class Library (.NET 8)
- [ ] Create `src/MarketAnalysis.Infrastructure` — Class Library (.NET 8)
- [ ] Add project references: Web → Core, Web → Infrastructure, Infrastructure → Core
- [ ] Verify `dotnet build` succeeds

### Step 0.2 — NuGet Packages
| Project | Package | Purpose |
|---------|---------|---------|
| Web | `MudBlazor` (v9.x) | UI component library |
| Web | `Blazor-ApexCharts` | Candlestick & financial charts |
| Web | `Hangfire.AspNetCore` | Job scheduling host |
| Infrastructure | `Hangfire.PostgreSql` | Hangfire storage in PostgreSQL |
| Infrastructure | `Npgsql.EntityFrameworkCore.PostgreSQL` | EF Core PostgreSQL provider |
| Infrastructure | `Microsoft.EntityFrameworkCore.Tools` | EF migrations CLI |
| Core | *(none initially)* | Pure domain models, no dependencies |

### Step 0.3 — Python FastAPI Project
- [ ] Create `src/MarketAnalysis.PythonService/` directory
- [ ] Create `requirements.txt` with initial deps:
  ```
  fastapi>=0.115.0
  uvicorn[standard]>=0.30.0
  yfinance[nospam]>=0.2.40
  pandas>=2.2.0
  pandas-ta>=0.3.14b
  numpy>=1.26.0
  transformers>=4.40.0
  torch>=2.2.0
  praw>=7.7.0
  requests>=2.31.0
  pydantic>=2.6.0
  python-dotenv>=1.0.0
  aiohttp>=3.9.0
  ```
- [ ] Create `main.py` with basic FastAPI app skeleton
- [ ] Create Python virtual environment (`python -m venv .venv`)
- [ ] Install dependencies, verify `uvicorn main:app` starts

### Step 0.4 — PostgreSQL Setup
- [ ] Docker Compose file for local PostgreSQL 16 instance
- [ ] Create `appsettings.Development.json` with connection string
- [ ] Verify EF Core can connect

### Step 0.5 — Docker Compose (optional, for full-stack local dev)
```yaml
services:
  postgres:
    image: postgres:16
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: market_analysis
      POSTGRES_USER: market
      POSTGRES_PASSWORD: dev_password
    volumes:
      - pgdata:/var/lib/postgresql/data
  python-api:
    build: ./src/MarketAnalysis.PythonService
    ports: ["8000:8000"]
    depends_on: [postgres]
  # web: run via `dotnet run` during dev for hot reload
volumes:
  pgdata:
```

**Exit Criteria:** `dotnet build` passes, Python service starts on port 8000, PostgreSQL accessible, MudBlazor renders a test page.

---

## Phase 1 — Domain Models & Database Schema

**Goal:** All EF Core entities defined, database created via migrations, repositories scaffolded.

### Step 1.1 — Core Domain Models (`MarketAnalysis.Core`)

```
src/MarketAnalysis.Core/
├── Entities/
│   ├── Stock.cs
│   ├── PriceHistory.cs
│   ├── TechnicalSignal.cs
│   ├── FundamentalSnapshot.cs
│   ├── SentimentScore.cs
│   ├── ScanReport.cs
│   ├── ScanReportEntry.cs
│   ├── UserScanConfig.cs
│   ├── WatchList.cs
│   ├── WatchListItem.cs
│   └── IndexDefinition.cs
├── Enums/
│   ├── PatternType.cs           # Flag, DoubleTop, DoubleBottom, HeadAndShoulders,
│   │                            # AscendingTriangle, DescendingTriangle,
│   │                            # SymmetricalTriangle, RisingWedge, FallingWedge,
│   │                            # Pennant, CupAndHandle, BullFlag, BearFlag
│   ├── SignalDirection.cs       # Bullish, Bearish, Neutral
│   ├── ReportCategory.cs        # DayTrade, SwingTrade, ShortTermHold, LongTermHold
│   ├── SentimentSource.cs       # News, Reddit, StockTwits
│   └── IndicatorType.cs         # RSI, MACD, BollingerBands, SMA, EMA, ADX, etc.
├── Interfaces/
│   ├── IStockRepository.cs
│   ├── IPriceHistoryRepository.cs
│   ├── ITechnicalSignalRepository.cs
│   ├── IFundamentalRepository.cs
│   ├── ISentimentRepository.cs
│   ├── IScanReportRepository.cs
│   ├── IWatchListRepository.cs
│   └── IPythonServiceClient.cs
└── DTOs/
    ├── MarketDataRequest.cs
    ├── MarketDataResponse.cs
    ├── TechnicalAnalysisRequest.cs
    ├── TechnicalAnalysisResponse.cs
    ├── PatternDetectionRequest.cs
    ├── PatternDetectionResponse.cs
    ├── SentimentRequest.cs
    ├── SentimentResponse.cs
    ├── FundamentalDataResponse.cs
    ├── ScanReportDto.cs
    └── UserScanConfigDto.cs
```

### Step 1.2 — Entity Details

**Stock**
| Field | Type | Notes |
|-------|------|-------|
| Id | int (PK) | Auto-increment |
| Ticker | string(10) | Unique index |
| Name | string(200) | Company name |
| Sector | string(100) | |
| Industry | string(100) | |
| Exchange | string(20) | NYSE, NASDAQ, etc. |
| MarketCap | decimal? | |
| IsActive | bool | Soft delete |
| LastUpdatedUtc | DateTime | |

**PriceHistory**
| Field | Type | Notes |
|-------|------|-------|
| Id | long (PK) | |
| StockId | int (FK) | Composite index: StockId + Date |
| Date | DateOnly | |
| Open | decimal | |
| High | decimal | |
| Low | decimal | |
| Close | decimal | |
| AdjClose | decimal | |
| Volume | long | |

**TechnicalSignal**
| Field | Type | Notes |
|-------|------|-------|
| Id | long (PK) | |
| StockId | int (FK) | |
| DetectedDate | DateOnly | |
| PatternType | PatternType (enum) | |
| Direction | SignalDirection (enum) | |
| Confidence | double | 0-100 |
| PatternStartDate | DateOnly | |
| PatternEndDate | DateOnly | |
| KeyPriceLevels | jsonb | Resistance, support, neckline, etc. |
| Metadata | jsonb | Additional pattern-specific data |

**FundamentalSnapshot**
| Field | Type | Notes |
|-------|------|-------|
| Id | long (PK) | |
| StockId | int (FK) | |
| SnapshotDate | DateOnly | |
| PERatio | double? | |
| ForwardPE | double? | |
| PEGRatio | double? | |
| PriceToBook | double? | |
| RevenuePerShare | double? | |
| EarningsPerShare | double? | |
| DebtToEquity | double? | |
| ProfitMargin | double? | |
| OperatingMargin | double? | |
| ReturnOnEquity | double? | |
| FreeCashFlow | decimal? | |
| DividendYield | double? | |
| Revenue | decimal? | |
| MarketCap | decimal? | |
| Beta | double? | |
| FiftyTwoWeekHigh | decimal? | |
| FiftyTwoWeekLow | decimal? | |
| RawData | jsonb | Full yfinance info dict backup |

**SentimentScore**
| Field | Type | Notes |
|-------|------|-------|
| Id | long (PK) | |
| StockId | int (FK) | |
| AnalysisDate | DateOnly | |
| Source | SentimentSource (enum) | |
| PositiveScore | double | 0.0 - 1.0 |
| NegativeScore | double | 0.0 - 1.0 |
| NeutralScore | double | 0.0 - 1.0 |
| SampleSize | int | Number of texts analyzed |
| Headlines | jsonb | Raw text samples collected |

**ScanReport**
| Field | Type | Notes |
|-------|------|-------|
| Id | int (PK) | |
| ReportDate | DateOnly | |
| Category | ReportCategory (enum) | |
| GeneratedAtUtc | DateTime | |
| ConfigSnapshot | jsonb | Copy of config used to generate |
| TotalStocksScanned | int | |
| TotalMatches | int | |

**ScanReportEntry**
| Field | Type | Notes |
|-------|------|-------|
| Id | long (PK) | |
| ScanReportId | int (FK) | |
| StockId | int (FK) | |
| CompositeScore | double | Weighted total score |
| TechnicalScore | double | |
| FundamentalScore | double | |
| SentimentScore | double | |
| Rank | int | Within this report |
| Reasoning | jsonb | Which criteria matched, scores breakdown |

**UserScanConfig**
| Field | Type | Notes |
|-------|------|-------|
| Id | int (PK) | |
| Name | string(100) | Config preset name |
| IsDefault | bool | |
| EnabledPatterns | PatternType[] | PostgreSQL array |
| PriceRangeMin | decimal? | |
| PriceRangeMax | decimal? | |
| MinMarketCap | decimal? | |
| MaxPERatio | double? | |
| MaxDebtToEquity | double? | |
| MinProfitMargin | double? | |
| MinSentimentScore | double? | |
| MinSentimentSampleSize | int | |
| TechnicalWeight | double | Weight for composite score (0-1) |
| FundamentalWeight | double | |
| SentimentWeight | double | |
| EnabledCategories | ReportCategory[] | Which report types to generate |
| EnabledSentimentSources | SentimentSource[] | |
| EnabledIndicators | IndicatorType[] | RSI, MACD, etc. |
| CreatedAtUtc | DateTime | |
| UpdatedAtUtc | DateTime | |

**WatchList / WatchListItem**
| Field | Type |
|-------|------|
| WatchList: Id, Name, Description, CreatedAtUtc | |
| WatchListItem: Id, WatchListId (FK), StockId (FK), AddedAtUtc | |

**IndexDefinition**
| Field | Type | Notes |
|-------|------|-------|
| Id | int (PK) | |
| Name | string(50) | "S&P 500", "NASDAQ 100" |
| IsEnabled | bool | Whether to include in daily scans |
| Tickers | string[] | PostgreSQL array of ticker symbols |
| LastRefreshedUtc | DateTime | |

### Step 1.3 — EF Core DbContext & Configuration
- [ ] Create `MarketAnalysisDbContext` in Infrastructure project
- [ ] Configure entity relationships, indexes, JSONB column mappings
- [ ] Key indexes:
  - `PriceHistory`: Unique on (StockId, Date), index on Date
  - `Stock`: Unique on Ticker
  - `TechnicalSignal`: Index on (StockId, DetectedDate)
  - `SentimentScore`: Index on (StockId, AnalysisDate, Source)
  - `ScanReport`: Index on (ReportDate, Category)
- [ ] Create initial EF migration
- [ ] Apply migration to dev database

### Step 1.4 — Repository Implementations
- [ ] Implement all repository interfaces in Infrastructure
- [ ] Generic base repository with common CRUD operations
- [ ] Specialized query methods (e.g., `GetLatestPriceHistory(stockId, days)`)

**Exit Criteria:** Database created with all tables, EF migrations applied, repositories unit-testable.

---

## Phase 2 — Python FastAPI Service — Data Fetching

**Goal:** Python service can fetch and return OHLCV data and fundamental data from Yahoo Finance.

### Step 2.1 — FastAPI App Structure
```
src/MarketAnalysis.PythonService/
├── main.py                      # FastAPI app, CORS, lifespan events
├── requirements.txt
├── Dockerfile
├── config.py                    # Settings (rate limits, API keys, etc.)
├── routers/
│   ├── __init__.py
│   ├── market_data.py           # /api/market-data/*
│   ├── technicals.py            # /api/technicals/*
│   ├── fundamentals.py          # /api/fundamentals/*
│   └── sentiment.py             # /api/sentiment/*
├── services/
│   ├── __init__.py
│   ├── yahoo_fetcher.py         # yfinance wrapper with rate limiting & caching
│   ├── indicator_engine.py      # pandas-ta indicator computation
│   ├── pattern_detector.py      # Custom chart pattern detection
│   ├── fundamental_analyzer.py  # Fundamental data extraction & scoring
│   ├── news_scraper.py          # Finnhub + RSS news fetching
│   ├── reddit_scraper.py        # PRAW Reddit data collection
│   ├── stocktwits_scraper.py    # StockTwits API integration
│   └── sentiment_analyzer.py    # FinBERT inference engine
├── models/
│   ├── __init__.py
│   ├── market_data.py           # Pydantic models for market data
│   ├── technicals.py            # Pydantic models for technical analysis
│   ├── fundamentals.py          # Pydantic models for fundamentals
│   └── sentiment.py             # Pydantic models for sentiment
└── utils/
    ├── __init__.py
    ├── rate_limiter.py          # Token bucket rate limiter for Yahoo
    └── ticker_lists.py          # S&P 500, NASDAQ 100 ticker management
```

### Step 2.2 — Yahoo Finance Data Fetcher (`yahoo_fetcher.py`)
- [ ] `fetch_ohlcv(tickers: list[str], period: str, interval: str)` — Uses `yf.download()` for bulk
- [ ] `fetch_fundamentals(ticker: str)` — Uses `Ticker.info` + `balance_sheet` + `income_stmt`
- [ ] `fetch_fundamentals_batch(tickers: list[str])` — Sequential with rate limiting
- [ ] Rate limiter: Max ~2000 requests/hour, delays between calls
- [ ] Install `yfinance[nospam]` (uses `curl_cffi` to avoid 429 errors)
- [ ] Error handling: retry logic with exponential backoff for transient failures
- [ ] Logging for all API calls

### Step 2.3 — Market Data Endpoints
- [ ] `POST /api/market-data/fetch-prices` — Input: tickers[], period, interval → Output: OHLCV DataFrame as JSON
- [ ] `POST /api/market-data/fetch-fundamentals` — Input: tickers[] → Output: fundamental data per ticker
- [ ] `GET /api/market-data/ticker-lists/{index_name}` — Returns current S&P 500 / NASDAQ 100 tickers (scraped from Wikipedia, cached)
- [ ] Health check endpoint: `GET /api/health`

### Step 2.4 — Ticker List Management
- [ ] Scrape S&P 500 tickers from Wikipedia table
- [ ] Scrape NASDAQ 100 tickers from Wikipedia
- [ ] Cache lists locally with TTL (refresh weekly)

**Exit Criteria:** Can call Python endpoints to get OHLCV and fundamental data for any ticker. Rate limiting prevents Yahoo 429 errors. Ticker lists for major indices available.

---

## Phase 3 — Python FastAPI Service — Technical Analysis

**Goal:** Compute technical indicators and detect chart patterns.

### Step 3.1 — Technical Indicator Engine (`indicator_engine.py`)
- [ ] Wrapper around `pandas-ta` for standard indicators:
  - Trend: SMA(20,50,200), EMA(9,21,50), MACD, ADX
  - Momentum: RSI(14), Stochastic, CCI, Williams %R
  - Volatility: Bollinger Bands, ATR, Keltner Channels
  - Volume: OBV, VWAP, Volume SMA
- [ ] Accept OHLCV data + list of requested indicators
- [ ] Return computed indicator values as structured JSON

### Step 3.2 — Chart Pattern Detector (`pattern_detector.py`)

Implement from scratch using pivot-point identification + geometric rule validation:

- [ ] **Utility: Pivot Point Identifier** — Find local highs/lows using rolling window approach
- [ ] **Utility: Trendline Fitter** — Linear regression on pivot points to identify support/resistance lines
- [ ] **Double Top** — Two peaks within N% price tolerance, separated by a trough, with breakdown below neckline
- [ ] **Double Bottom** — Inverse of double top logic
- [ ] **Head & Shoulders** — Three peaks: left shoulder, head (highest), right shoulder (similar to left), neckline validation
- [ ] **Inverse Head & Shoulders** — Mirror of H&S
- [ ] **Bull Flag** — Strong upward pole (>5% in <10 bars) + tight downward-sloping parallel channel consolidation
- [ ] **Bear Flag** — Inverse of bull flag
- [ ] **Ascending Triangle** — Flat resistance + rising support (higher lows)
- [ ] **Descending Triangle** — Flat support + falling resistance (lower highs)
- [ ] **Symmetrical Triangle** — Converging support and resistance
- [ ] **Rising Wedge** — Both lines rising but converging (bearish)
- [ ] **Falling Wedge** — Both lines falling but converging (bullish)
- [ ] **Pennant** — Small symmetrical triangle after a strong move (pole)
- [ ] **Cup and Handle** — U-shaped base (cup) + small consolidation (handle) + breakout

Each detector returns:
```json
{
  "pattern_type": "double_top",
  "direction": "bearish",
  "confidence": 78.5,
  "start_date": "2026-01-10",
  "end_date": "2026-02-05",
  "key_levels": {
    "resistance": 185.50,
    "neckline": 172.30,
    "target": 159.10
  },
  "status": "forming | confirmed | failed",
  "metadata": {}
}
```

### Step 3.3 — Technical Analysis Endpoints
- [ ] `POST /api/technicals/indicators` — Input: OHLCV data + requested indicators → Output: indicator values
- [ ] `POST /api/technicals/patterns` — Input: OHLCV data + requested patterns → Output: detected patterns with confidence
- [ ] `POST /api/technicals/full-analysis` — Combined indicators + patterns in one call

**Exit Criteria:** All 15 chart patterns detectable with confidence scoring. Indicators computing correctly against known test data. Pattern detection validated against visual chart inspection.

---

## Phase 4 — Python FastAPI Service — Sentiment Analysis

**Goal:** Collect text from news/Reddit/StockTwits and score with FinBERT.

### Step 4.1 — News Scraper (`news_scraper.py`)
- [ ] Finnhub integration: `/company-news?symbol={ticker}&from=...&to=...` (free API key required)
- [ ] Google News RSS fallback: parse RSS feed for `"{company_name}" OR "${ticker}" stock`
- [ ] De-duplicate headlines across sources
- [ ] Return list of `{source, headline, url, published_date}` per ticker

### Step 4.2 — Reddit Scraper (`reddit_scraper.py`)
- [ ] PRAW setup: search r/wallstreetbets, r/stocks, r/investing
- [ ] Search for ticker mentions (handle $TICKER and TICKER formats)
- [ ] Collect post titles + top comment bodies (last 24-48h)
- [ ] Filter noise: minimum upvote threshold, minimum text length
- [ ] Rate limit compliance with Reddit API

### Step 4.3 — StockTwits Scraper (`stocktwits_scraper.py`)
- [ ] Public API: `GET https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json`
- [ ] No auth needed for basic access (30 messages per call)
- [ ] Extract message bodies
- [ ] Handle rate limits (200 requests/hour for unauthenticated)

### Step 4.4 — FinBERT Sentiment Analyzer (`sentiment_analyzer.py`)
- [ ] Load `ProsusAI/finbert` model on startup (cache locally)
- [ ] Batch inference: process multiple texts efficiently
- [ ] Per-text output: `{positive, negative, neutral}` probabilities
- [ ] Per-ticker aggregation: weighted average across all texts from a source
- [ ] GPU support if available, fallback to CPU
- [ ] Model warm-up on service start to avoid first-request latency

### Step 4.5 — Sentiment Endpoints
- [ ] `POST /api/sentiment/collect` — Input: tickers[] + sources[] → Output: raw text collected per ticker per source
- [ ] `POST /api/sentiment/analyze` — Input: texts[] → Output: FinBERT scores per text
- [ ] `POST /api/sentiment/full-pipeline` — Input: tickers[] + sources[] → Output: aggregated scores per ticker per source (collect + analyze combined)

**Exit Criteria:** Can collect text from all 3 sources and score with FinBERT. Aggregated scores return per-ticker sentiment with sample sizes. Model loads in <30s, inference <500ms/batch on CPU.

---

## Phase 5 — .NET Backend — Infrastructure & Python Client

**Goal:** .NET backend can call Python service, store results in PostgreSQL, and serve data to frontend.

### Step 5.1 — Python Service HTTP Client (`IPythonServiceClient`)
- [ ] Typed HTTP client using `IHttpClientFactory` with base address from config
- [ ] Methods mapping to each Python endpoint:
  - `FetchPricesAsync(tickers, period, interval)`
  - `FetchFundamentalsAsync(tickers)`
  - `RunIndicatorsAsync(ohlcvData, indicators)`
  - `DetectPatternsAsync(ohlcvData, patterns)`
  - `RunSentimentPipelineAsync(tickers, sources)`
  - `GetTickerListAsync(indexName)`
- [ ] Retry policies with Polly (transient HTTP errors, timeout)
- [ ] Circuit breaker in case Python service is down
- [ ] Response deserialization to Core DTOs

### Step 5.2 — Data Ingestion Service
- [ ] `IMarketDataIngestionService` — Orchestrates fetching data from Python and storing in PostgreSQL
- [ ] `IngestPriceData(tickers)` → Calls Python, maps to `PriceHistory` entities, upserts
- [ ] `IngestFundamentals(tickers)` → Calls Python, maps to `FundamentalSnapshot`, upserts
- [ ] `IngestTechnicals(tickers, config)` → Calls Python, maps to `TechnicalSignal`, saves
- [ ] `IngestSentiment(tickers, sources)` → Calls Python, maps to `SentimentScore`, saves
- [ ] Bulk insert optimization (EF Core `AddRange` + `SaveChanges` in batches)

### Step 5.3 — Report Generation Engine
- [ ] `IReportGenerationService` — Scores and classifies stocks into report categories
- [ ] Scoring algorithm per category:
  ```
  CompositeScore = (TechnicalScore × TechnicalWeight) 
                 + (FundamentalScore × FundamentalWeight) 
                 + (SentimentScore × SentimentWeight)
  ```
- [ ] **Day Trade scoring**: High volume (>1.5x avg), ATR/price ratio >2%, bullish pattern forming, positive 24h sentiment, price in user's range
- [ ] **Swing Trade scoring**: Pattern near breakout (flag/triangle at apex), RSI recovering from <30 or overbought >70 reversal, moderate volume, 3-10 day expected hold
- [ ] **Short-Term Hold scoring**: Confirmed bullish pattern, positive fundamental trend (quarter-over-quarter), positive sentiment trend, 2-8 week horizon
- [ ] **Long-Term Hold scoring**: P/E below sector average, positive FCF, low debt/equity, consistent revenue growth, strong long-term sentiment
- [ ] Apply user's `UserScanConfig` filters (price range, enabled patterns, fundamental thresholds)
- [ ] Rank stocks within each category by composite score
- [ ] Generate `ScanReport` + `ScanReportEntry` records

### Step 5.4 — API Controllers
- [ ] `ReportsController` — GET reports by date/category, GET report detail
- [ ] `StocksController` — GET stock detail, GET price history, GET technicals, GET sentiment
- [ ] `WatchListsController` — CRUD watchlists
- [ ] `ConfigController` — GET/PUT scan configuration
- [ ] `JobsController` — Trigger manual scan, get job status
- [ ] `DashboardController` — Aggregated data for dashboard widgets

**Exit Criteria:** Full pipeline works end-to-end from data fetch → analysis → report generation → API serving. Reports contain ranked stocks with score breakdowns.

---

## Phase 6 — Hangfire Job Scheduling

**Goal:** Daily automated pipeline runs after market close.

### Step 6.1 — Hangfire Setup
- [ ] Register Hangfire services with PostgreSQL storage
- [ ] Configure Hangfire dashboard (route: `/hangfire`)
- [ ] Dashboard authorization (restrict in production)

### Step 6.2 — Daily Scan Pipeline Job
- [ ] `DailyScanJob` class with `Execute()` method
- [ ] Schedule: `RecurringJob.AddOrUpdate("daily-scan", () => job.Execute(), "0 18 * * 1-5")` (6 PM ET, weekdays)
- [ ] Pipeline steps (sequential with parallel sub-steps):
  ```
  1. Resolve ticker universe (watchlists + enabled indexes)
  2. [Parallel] Fetch prices | Fetch fundamentals (weekly)
  3. Store price & fundamental data
  4. [Parallel] Run technicals | Run sentiment
  5. Store technical signals & sentiment scores
  6. Generate reports for each enabled category
  7. Store reports
  8. (Future) Send notifications
  ```
- [ ] Job progress tracking: log each step completion
- [ ] Error handling: if one ticker fails, continue with others; log failures
- [ ] Configurable: respect `UserScanConfig` for which patterns/sources to use

### Step 6.3 — Supporting Jobs
- [ ] `RefreshIndexTickersJob` — Weekly job to refresh S&P 500 / NASDAQ 100 ticker lists
- [ ] `CleanupOldDataJob` — Monthly job to purge price history older than N years (configurable)
- [ ] Manual trigger endpoint: `POST /api/jobs/run-scan` — queues an immediate scan

**Exit Criteria:** Hangfire dashboard accessible, daily job runs at scheduled time, job progress visible, manual trigger works.

---

## Phase 7 — Blazor Server Frontend

**Goal:** Full interactive dashboard for viewing reports, configuring scans, and managing watchlists.

### Step 7.1 — Layout & Navigation
```
Pages/
├── Dashboard.razor              # Main landing page
├── Reports/
│   ├── ReportList.razor         # Reports by date
│   └── ReportDetail.razor       # Single report with ranked stocks
├── Stocks/
│   └── StockDetail.razor        # Deep-dive on a single stock
├── Configuration/
│   └── ScanConfig.razor         # Full configuration page
├── WatchLists/
│   ├── WatchListIndex.razor     # List of watchlists
│   └── WatchListEdit.razor      # Edit a watchlist
└── Jobs/
    └── JobStatus.razor          # Scan job history and manual trigger

Components/
├── Charts/
│   ├── CandlestickChart.razor   # ApexCharts candlestick with pattern overlays
│   ├── IndicatorChart.razor     # RSI, MACD sub-charts
│   └── SentimentGauge.razor     # Sentiment score visualization
├── Cards/
│   ├── StockCard.razor          # Summary card for a stock pick
│   ├── ReportSummaryCard.razor  # Category summary (DayTrade, Swing, etc.)
│   └── FundamentalsCard.razor   # Key fundamental metrics display
├── Tables/
│   ├── StockRankingTable.razor  # Sortable ranked stock list
│   └── PriceHistoryTable.razor  # OHLCV data table
├── Config/
│   ├── PatternSelector.razor    # Multi-select checkboxes for chart patterns
│   ├── PriceRangeSlider.razor   # Min/max price slider
│   ├── FundamentalFilters.razor # P/E, debt, margin threshold inputs
│   ├── SentimentConfig.razor    # Source toggles & weight sliders
│   └── CategoryWeights.razor    # Technical/Fundamental/Sentiment weight sliders
└── Shared/
    ├── ScoreBar.razor           # Visual score indicator (0-100)
    └── TickerSearch.razor       # Autocomplete ticker search
```

### Step 7.2 — Dashboard Page
- [ ] Top row: 4 `ReportSummaryCard` components (Day Trade, Swing, Short Hold, Long Hold)
  - Each shows: # of picks, top 3 stocks with scores, last scan time
- [ ] Middle row: "Today's Top Picks" — best stock from each category with mini candlestick chart
- [ ] Bottom row: Recent scan job status, next scheduled run time
- [ ] Auto-refresh via SignalR (Blazor Server built-in)

### Step 7.3 — Report Detail Page
- [ ] Category tabs (Day Trade | Swing Trade | Short Hold | Long Hold)
- [ ] MudBlazor DataGrid with columns: Rank, Ticker, Name, Price, Composite Score, Technical Score, Fundamental Score, Sentiment Score, Pattern, Direction
- [ ] Expandable row detail: candlestick chart, detected patterns highlighted, fundamental metrics table, sentiment breakdown by source
- [ ] Sortable, filterable, paginated
- [ ] Export to CSV button

### Step 7.4 — Stock Detail Page
- [ ] Full candlestick chart (ApexCharts) with:
  - Configurable time range (1M, 3M, 6M, 1Y)
  - SMA/EMA overlays toggleable
  - Pattern annotations (rectangles/lines marking detected patterns)
- [ ] Sub-charts: RSI, MACD, Volume
- [ ] Fundamentals panel: key metrics in a grid layout
- [ ] Sentiment timeline: line chart showing sentiment scores over time, per source
- [ ] Recent signals table: list of all detected patterns with dates and confidence

### Step 7.5 — Configuration Page
- [ ] **Pattern Selection**: Checklist of all 15+ chart patterns with descriptions, "Select All" / "Clear All"
- [ ] **Price Range**: Dual-handle slider for min/max stock price (e.g., $1 - $500)
- [ ] **Fundamental Filters**: Input fields for max P/E, min profit margin, max debt/equity, min market cap, etc.
- [ ] **Sentiment Settings**: Toggle switches for News/Reddit/StockTwits, minimum sample size slider, source weight sliders
- [ ] **Category Weights**: Three sliders per report category (Technical/Fundamental/Sentiment weights, must sum to 1.0)
- [ ] **Indicator Selection**: Checkboxes for which technical indicators to compute
- [ ] Save as named preset, load presets, set default preset
- [ ] "Apply & Run Scan" button: saves config and triggers manual scan

### Step 7.6 — Watchlist Management
- [ ] CRUD for watchlists (name, description)
- [ ] Ticker search with autocomplete (search by ticker or company name)
- [ ] Add/remove tickers from watchlist
- [ ] Toggle index scans (S&P 500, NASDAQ 100) on/off
- [ ] Display: last scan results for each ticker in watchlist

### Step 7.7 — Job Status Page
- [ ] Simplified view of Hangfire job history (last 20 runs)
- [ ] Status badges: Running, Succeeded, Failed
- [ ] Duration, start time, tickers scanned count
- [ ] "Run Now" button to trigger immediate scan
- [ ] Link to full Hangfire dashboard for advanced users

**Exit Criteria:** All pages render with real data from the API. Configuration saves and applies to subsequent scans. Charts display correctly with pattern overlays.

---

## Phase 8 — Testing & Validation

### Step 8.1 — Python Unit Tests
- [ ] Pattern detector tests against known historical data (verified patterns from TradingView)
- [ ] Indicator engine output matches known values (compare against TradingView/manual calc)
- [ ] Sentiment analyzer returns consistent scores for known positive/negative financial text
- [ ] Yahoo fetcher tests (mock responses for rate limit handling, error recovery)

### Step 8.2 — .NET Unit Tests
- [ ] Report generation scoring tests with known inputs
- [ ] Repository tests (in-memory DbContext provider or Testcontainers with PostgreSQL)
- [ ] Python service client tests with mock HTTP responses

### Step 8.3 — Integration Tests
- [ ] End-to-end: small watchlist (5 tickers) → full pipeline → report generation
- [ ] Verify data flows: yfinance → Python analysis → .NET storage → Blazor display
- [ ] Hangfire job execution test

### Step 8.4 — Manual Validation
- [ ] Compare detected patterns against TradingView charts visually (10 stocks, 5 chart patterns each)
- [ ] Verify fundamental data matches Yahoo Finance website
- [ ] Read sentiment headlines and verify FinBERT scores make sense
- [ ] Review generated reports for reasonableness

---

## Phase 9 — Polish & Production Readiness

### Step 9.1 — Error Handling & Resilience
- [ ] Global exception handling middleware (.NET)
- [ ] Structured logging (Serilog → console + file)
- [ ] Python service structured logging
- [ ] Graceful degradation: if sentiment fails, still generate report with technicals + fundamentals

### Step 9.2 — Performance
- [ ] Batch processing: process tickers in chunks (50 at a time) to manage memory
- [ ] Cache FinBERT model in memory (load once on startup)
- [ ] Cache S&P 500 ticker list (refresh weekly)
- [ ] EF Core query optimization: no N+1 queries, proper `.Include()` usage
- [ ] Index tuning in PostgreSQL based on query patterns

### Step 9.3 — Configuration & Environment
- [ ] `appsettings.json` / `.env` for all configurable values
- [ ] API keys (Finnhub, Reddit) in user secrets / environment variables
- [ ] Python service settings in `config.py` / `.env`

### Step 9.4 — Documentation
- [ ] README with setup instructions (prerequisites, database setup, API keys needed)
- [ ] FastAPI auto-generated Swagger docs at `/docs`
- [ ] In-app help tooltips on configuration page

---

## Implementation Priority / Suggested Build Order

| Order | Phase | Estimated Effort | Dependency |
|-------|-------|-----------------|------------|
| 1 | Phase 0 — Scaffolding | 1-2 days | None |
| 2 | Phase 1 — Domain Models & DB | 2-3 days | Phase 0 |
| 3 | Phase 2 — Python Data Fetching | 2-3 days | Phase 0 |
| 4 | Phase 3 — Python Technicals | 5-7 days | Phase 2 |
| 5 | Phase 4 — Python Sentiment | 3-4 days | Phase 2 |
| 6 | Phase 5 — .NET Backend | 4-5 days | Phase 1, 2, 3, 4 |
| 7 | Phase 6 — Hangfire Scheduling | 1-2 days | Phase 5 |
| 8 | Phase 7 — Blazor Frontend | 7-10 days | Phase 5 |
| 9 | Phase 8 — Testing | 3-5 days | Phase 7 |
| 10 | Phase 9 — Polish | 2-3 days | Phase 8 |
| | **Total** | **~30-44 days** | |

> **Note:** Phases 2, 3, 4 (Python service) can be built in parallel with Phase 1 (database schema). Phase 7 (frontend) can start page shells while backend APIs are being built.

---

## Prerequisites to Gather Before Starting

- [ ] **PostgreSQL** installed locally or Docker available
- [ ] **Python 3.12+** installed
- [ ] **.NET 8 SDK** installed
- [ ] **Finnhub API key** (free tier: https://finnhub.io/register)
- [ ] **Reddit API credentials** (create app at https://www.reddit.com/prefs/apps)
- [ ] **~4GB disk space** for FinBERT model download (first run)
- [ ] **Node.js** (optional, only if Blazor WASM needed later)
