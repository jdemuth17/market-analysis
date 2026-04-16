# Services — Ollama Cloud Integration & Analysis Pipeline

## Ollama Cloud Architecture

### Singleton Pattern & Lifecycle

`OllamaClient` is instantiated once during FastAPI app startup (in `main.py` lifespan) and stored in `app.state.ollama_client`. All services receive it via dependency injection. No per-request instantiation.

### Concurrency Control

**asyncio.Semaphore(3)**: Gates all Ollama Cloud API calls. Ollama Pro allows 3 concurrent cloud models maximum. The semaphore enforces this limit across all requests (sentiment, reports). 4th concurrent request blocks until one completes.

### Queue-and-Retry with Exponential Backoff

**Request Queue**: `asyncio.Queue(maxsize=1000)` holds failed requests for background retry. Queue depth prevents unbounded memory growth during extended outages.

**TTL**: Items older than 1 hour (configurable via `MA_OLLAMA_QUEUE_TTL_SECONDS`) are discarded. Balances retry window vs stale data.

**Exponential Backoff**: 3 retry attempts at 1s/2s/4s intervals (configurable via `MA_OLLAMA_RETRY_MAX_ATTEMPTS`, `MA_OLLAMA_RETRY_BASE_DELAY`). Handles transient 429/503 responses and network timeouts.

**Background Consumer**: Async task started via `start_queue_consumer()` drains the queue continuously. Stops gracefully on shutdown via `stop()`.

### Error Handling

- **429/503 (Rate Limit/Unavailable)**: Retry with exponential backoff. After exhausting retries, enqueue for background processing.
- **Network Timeout**: Enqueue immediately for background retry.
- **Queue Full**: Raises `OllamaQueueFullError`. Callers degrade to VADER fallback.
- **Invalid API Key**: Logs warning, sets `_client = None`. Service operates in VADER-only mode.

## Models

### qwen3.5 (Sentiment Analysis)

**Purpose**: Financial sentiment classification with structured JSON output.

**Usage**: `sentiment_analyzer.py` calls `OllamaClient.chat()` with `format_schema=SentimentAnalysisResponse.model_json_schema()`.

**Output**: `{positive: float, negative: float, neutral: float, label: str}`

**Why qwen3.5**: Excels at instruction-following with structured formats. Cheaper than deepseek for simple classification. FinBERT-compatible output via Ollama `format` parameter.

### deepseek-v3.2 (Analyst Reports)

**Purpose**: Multi-step reasoning for comprehensive stock analysis with trade level suggestions.

**Usage**: `ai_report_generator.py` sends price history (30 bars), technicals, fundamentals, sentiment to deepseek-v3.2.

**Output**: `AnalystReportResponse` with summary, outlook, key_factors, risk_factors, recommendation, confidence, trade_levels.

**Context Window**: 32K. Prompts capped at 4K tokens (configurable via `MA_AI_MAX_PROMPT_TOKENS`) to leave room for output.

**Why deepseek-v3.2**: Best at chain-of-thought analysis across multiple data sources. Context-aware trade levels vs formula-based ATR.

### VADER Fallback

**When**: Ollama API key missing/invalid, queue full, or network failure after retries.

**Provider**: `vaderSentiment.SentimentIntensityAnalyzer` (lexicon-based, local, 3MB).

**Output**: Compatible `SentimentResult(text, positive, negative, neutral, label)`. Preserves contract for .NET side.

**Lazy Loading**: VADER loaded on first fallback use via `_get_vader()` to avoid import overhead when Ollama is healthy.

## Configuration

All settings loaded via environment variables with `MA_` prefix (defined in `config.py`):

| Variable                          | Default                      | Purpose                                    |
|-----------------------------------|------------------------------|--------------------------------------------|
| `MA_OLLAMA_API_KEY`               | `""`                         | Bearer token for Ollama Cloud API          |
| `MA_OLLAMA_BASE_URL`              | `https://api.ollama.com`     | Ollama Cloud endpoint                      |
| `MA_OLLAMA_SENTIMENT_MODEL`       | `qwen3.5`                    | Model for sentiment classification         |
| `MA_OLLAMA_REASONING_MODEL`       | `deepseek-v3.2`              | Model for analyst reports                  |
| `MA_OLLAMA_QUEUE_MAX`             | `1000`                       | Max queue depth before rejecting requests  |
| `MA_OLLAMA_QUEUE_TTL_SECONDS`     | `3600`                       | Max age of queued items before discard     |
| `MA_OLLAMA_RETRY_MAX_ATTEMPTS`    | `3`                          | Retry attempts before queuing              |
| `MA_OLLAMA_RETRY_BASE_DELAY`      | `1.0`                        | Base delay (seconds) for exponential backoff|
| `MA_OLLAMA_TIMEOUT_SECONDS`       | `60`                         | HTTP request timeout                       |
| `MA_AI_PRICE_BAR_COUNT`           | `30`                         | Historical bars sent to analyst LLM        |
| `MA_AI_MAX_PROMPT_TOKENS`         | `4000`                       | Prompt length cap for analyst reports      |
| `MA_AI_BATCH_MAX`                 | `20`                         | Max tickers in batch AI analysis           |
| `MA_AI_AUTO_REPORT_COUNT`         | `5`                          | Auto-reports generated per scan category   |

## Service Files

- **`ollama_client.py`**: Core HTTP client with semaphore, queue, retry logic. Single source for all Ollama Cloud interactions.
- **`sentiment_analyzer.py`**: Calls Ollama (qwen3.5) or VADER. Preserves existing `SentimentResult` contract for .NET compatibility.
- **`ai_report_generator.py`**: Assembles prompts from price/technical/fundamental/sentiment data. Calls Ollama (deepseek-v3.2) with structured output schema.
- **`indicator_engine.py`**: Calculates RSI, MACD, moving averages. Provides technical data for analyst prompts.
- **`pattern_detector.py`**: Detects chart patterns (triangles, head-and-shoulders, etc.). Feeds into analyst context.
- **`yahoo_fetcher.py`**: Fetches price history, fundamentals. Primary data source for prompts.
- **`news_scraper.py`**: Collects news headlines for sentiment analysis.
- **`reddit_scraper.py`**: Scrapes Reddit mentions via PRAW for sentiment.
- **`stocktwits_scraper.py`**: Fetches StockTwits posts for sentiment.
- **`fundamental_analyzer.py`**: Aggregates fundamental metrics (PE, debt-to-equity, ROE). Used in analyst prompts.
