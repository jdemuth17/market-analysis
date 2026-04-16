# MarketAnalysis.PythonService

FastAPI service for market data fetching, sentiment analysis, technical indicators, and AI-powered analyst reports.

## Files

| File             | What                                           | When to read                                        |
|------------------|------------------------------------------------|-----------------------------------------------------|
| `main.py`        | FastAPI app, routes, lifespan startup/shutdown | Adding endpoints, modifying app lifecycle           |
| `config.py`      | Pydantic settings with MA_ env var loading     | Adding config options, environment setup            |
| `requirements.txt` | Python dependencies                          | Installing packages, resolving version conflicts    |
| `Dockerfile`     | Container build for production deployment      | Modifying container image, adding system deps       |

## Subdirectories

| Directory     | What                                           | When to read                                        |
|---------------|------------------------------------------------|-----------------------------------------------------|
| `services/`   | Ollama client, sentiment, AI reports, scrapers | Implementing analysis features, debugging Ollama    |
| `models/`     | Pydantic request/response schemas              | Adding API endpoints, modifying data contracts      |
| `routers/`    | FastAPI route handlers by feature area         | Adding routes, understanding endpoint logic         |
| `utils/`      | Helper functions, formatters, validators       | Reusing common logic, debugging utilities           |
| `tests/`      | Unit and integration tests                     | Writing tests, debugging failures                   |

## Build

```bash
pip install -r requirements.txt
```

## Test

```bash
pytest tests/ -v
```

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
