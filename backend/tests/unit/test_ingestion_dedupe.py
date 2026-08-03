from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.domain.models import DocumentKind, Exchange, SourceDocument, Stock
from app.embeddings import DeterministicEmbedder
from app.ingestion import IngestionService
from app.repositories.memory import InMemoryResearchRepository
from app.tagging import ResilientArticleTagger


class SyndicatedProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, ticker: str):
        self.calls += 1
        stock = Stock(
            ticker="TCS",
            exchange=Exchange.NSE,
            name="Tata Consultancy Services",
            price_inr=Decimal(4100),
        )
        suffix = "first" if self.calls == 1 else "second"
        story = SourceDocument.create(
            ticker="TCS",
            kind=DocumentKind.NEWS,
            title="TCS wins a major cloud order",
            url=f"https://{suffix}.example.test/tcs-order",
            content=f"{suffix.title()} publisher summary of the TCS cloud order.",
            published_at=datetime(2026, 8, 3, tzinfo=UTC),
            sentiment=0.5,
        )
        return stock, (story,)


async def test_ingestion_skips_existing_syndicated_story_before_embedding() -> None:
    repository = InMemoryResearchRepository()
    embedder = DeterministicEmbedder(dimensions=16)
    service = IngestionService(
        repository,
        SyndicatedProvider(),
        embedder,
        ResilientArticleTagger(),
    )

    first = await service.ingest("TCS")
    second = await service.ingest("TCS")

    assert first.inserted == 1
    assert second.inserted == 0
    assert second.skipped == 1
    assert second.sentiment == first.sentiment == 0.5
    assert await repository.count_documents("TCS") == 1
    assert (await repository.get_stock("TCS")).sentiment == 0.5
    assert embedder.embedded_count == 1
