FROM python:3.11-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
RUN python -m venv /opt/venv
COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM gcr.io/distroless/python3-debian12:nonroot AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/opt/venv/lib/python3.11/site-packages" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    PORT=8000

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=65532:65532 alembic.ini ./
COPY --chown=65532:65532 alembic ./alembic
COPY --chown=65532:65532 app ./app
EXPOSE 8000
CMD ["-m", "uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
