# Bridge Backend

FastAPI backend for the Bridge app. Dependencies managed with [uv](https://github.com/astral-sh/uv).

## Setup

```bash
uv sync
```

## Run

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API available at http://localhost:8000  
Health check: http://localhost:8000/api/health
