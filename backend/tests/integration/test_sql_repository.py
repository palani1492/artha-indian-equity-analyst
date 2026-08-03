from __future__ import annotations

import asyncio
import os

import pytest

from app.container import build_container
from app.settings import Settings


async def test_postgres_pgvector_ingestion_is_concurrent_idempotent_and_searchable(
) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is available in CI's pgvector job")

    container = build_container(
        Settings(
            app_env="test",
            auth_mode="demo",
            database_url=database_url,
            market_data_provider="demo",
        )
    )
    try:
        assert await container.repository.healthcheck() is True

        first, second = await asyncio.gather(
            container.ingestion.ingest("INFY"),
            container.ingestion.ingest("INFY"),
        )
        document_count = await container.repository.count_documents("INFY")

        assert first.inserted + second.inserted == document_count
        assert document_count > 0
        assert {first.inserted == 0, second.inserted == 0} == {False, True}

        query = await container.embedder.embed("INFY revenue price sentiment")
        matches = await container.repository.search_documents(
            query, tickers=("INFY",), limit=3
        )
        assert matches
        assert all(document.ticker == "INFY" for document in matches)
    finally:
        await container.repository.engine.dispose()
