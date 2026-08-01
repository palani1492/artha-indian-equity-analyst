# Sentellent backend

FastAPI + LangGraph backend for grounded Indian-equity research. The default demo provider is deterministic and network-free. Production live mode uses yfinance for INR-market fundamentals and rate-limited configurable Indian financial RSS feeds. OpenAI generation/embeddings are optional; provider errors fall back to deterministic local behavior.

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.api:app --reload --port 8000
```

For a no-database demo, remove `DATABASE_URL`; data remains in memory for the process lifetime. Never use `AUTH_MODE=demo` in production. Google OIDC requires `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and a random `SESSION_SECRET`. The callback validates state and nonce and issues an opaque, repository-backed `HttpOnly; Secure; SameSite=Lax` session cookie.

## Verification and scheduled refresh

```bash
.venv/bin/pytest --cov=app --cov-report=term-missing
.venv/bin/ruff check app tests
.venv/bin/mypy app
.venv/bin/pip-audit -r requirements.txt
python -m app.jobs.ingest --all-followed
```

The canonical API is under `/api/v1`; unversioned aliases exist for the frontend. `GET /health` is public for load balancers.

