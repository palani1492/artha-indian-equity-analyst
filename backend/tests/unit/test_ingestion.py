from __future__ import annotations

import asyncio

from app.ingestion import IngestionService


async def test_ingestion_is_idempotent(container) -> None:
    service: IngestionService = container.ingestion
    first = await service.ingest("TCS")
    second = await service.ingest("TCS")

    assert first.inserted > 0
    assert second.inserted == 0
    assert second.skipped == first.inserted + first.skipped
    assert await container.repository.count_documents("TCS") == first.inserted
    assert container.embedder.embedded_count == first.inserted
    news = [
        document
        for document in await container.repository.list_documents("TCS")
        if document.kind == "news"
    ]
    assert news[0].mentioned_tickers == ("TCS",)


async def test_concurrent_ingestion_uses_per_ticker_lock_and_does_not_double_embed(
    container,
) -> None:
    first, second = await asyncio.gather(
        container.ingestion.ingest("RELIANCE"),
        container.ingestion.ingest("RELIANCE"),
    )
    count = await container.repository.count_documents("RELIANCE")

    assert first.inserted + second.inserted == count
    assert container.embedder.embedded_count == count
    assert {first.inserted == 0, second.inserted == 0} == {False, True}


async def test_different_tickers_can_ingest_independently(container) -> None:
    tcs, infy = await asyncio.gather(
        container.ingestion.ingest("TCS"),
        container.ingestion.ingest("INFY"),
    )
    assert tcs.inserted > 0
    assert infy.inserted > 0


async def test_ingestion_preserves_explicit_bse_exchange(container) -> None:
    await container.ingestion.ingest("TCS.BO")
    stock = await container.repository.get_stock("TCS")
    assert stock is not None
    assert stock.exchange == "BSE"
