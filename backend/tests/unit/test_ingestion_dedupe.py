from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.agent import EquityResearchAgent
from app.domain.models import DocumentKind, Exchange, SourceDocument, Stock
from app.embeddings import DeterministicEmbedder
from app.generation import ClaimPreservingAnswerGenerator, DeterministicAnswerGenerator
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


class MahindraProvider:
    async def fetch(self, ticker: str):
        stock = Stock(
            ticker="M&M",
            exchange=Exchange.NSE,
            name="Mahindra & Mahindra Limited",
            price_inr=Decimal(3000),
            pe_ratio=Decimal("18.5"),
            debt_to_equity=Decimal("0.7"),
        )
        fundamentals = SourceDocument.create(
            ticker="M&M",
            kind=DocumentKind.FUNDAMENTALS,
            title="Mahindra & Mahindra fundamentals",
            url="https://finance.example.test/m-and-m",
            content=(
                "Mahindra & Mahindra price is INR 3000. P/E ratio is 18.5. "
                "Debt-to-equity is 0.7."
            ),
            published_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        return stock, (fundamentals,)


class SparseComparisonProvider:
    async def fetch(self, ticker: str):
        if ticker == "M&M":
            return await MahindraProvider().fetch(ticker)
        stock = Stock(
            ticker="TCS",
            exchange=Exchange.NSE,
            name="Tata Consultancy Services",
            price_inr=Decimal(4100),
            pe_ratio=Decimal("22.0"),
        )
        fundamentals = SourceDocument.create(
            ticker="TCS",
            kind=DocumentKind.FUNDAMENTALS,
            title="Tata Consultancy Services fundamentals",
            url="https://finance.example.test/tcs",
            content="Tata Consultancy Services price is INR 4100. P/E ratio is 22.",
            published_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        return stock, (fundamentals,)


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


async def test_ingestion_removes_stale_unrelated_news_but_preserves_fundamentals() -> None:
    repository = InMemoryResearchRepository()
    embedder = DeterministicEmbedder(dimensions=16)
    stale_article = SourceDocument.create(
        ticker="M&M",
        kind=DocumentKind.NEWS,
        title="Bharti Airtel Q1 results surprise investors",
        url="https://news.example.test/bharti",
        content="Bharti Airtel reported stronger telecom demand.",
        published_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    valid_article = SourceDocument.create(
        ticker="M&M",
        kind=DocumentKind.NEWS,
        title="Mahindra SUV demand remains firm",
        url="https://news.example.test/mahindra",
        content="Mahindra reported firm SUV demand.",
        published_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    stock = await MahindraProvider().fetch("M&M")
    await repository.upsert_stock(stock[0])
    await repository.insert_document(stale_article, await embedder.embed(stale_article.content))
    await repository.insert_document(valid_article, await embedder.embed(valid_article.content))

    service = IngestionService(
        repository,
        MahindraProvider(),
        embedder,
        ResilientArticleTagger(),
    )
    await service.ingest("M&M")

    documents = await repository.list_documents("M&M")
    assert all("Bharti" not in document.title for document in documents)
    assert any(document.kind is DocumentKind.FUNDAMENTALS for document in documents)
    assert any("Mahindra SUV" in document.title for document in documents)


async def test_sparse_comparison_stays_grounded_after_stale_news_cleanup() -> None:
    repository = InMemoryResearchRepository()
    embedder = DeterministicEmbedder(dimensions=16)
    stale_article = SourceDocument.create(
        ticker="M&M",
        kind=DocumentKind.NEWS,
        title="Bharti Airtel Q1 results surprise investors",
        url="https://news.example.test/bharti-comparison",
        content="Bharti Airtel reported stronger telecom demand.",
        published_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    await repository.insert_document(stale_article, await embedder.embed(stale_article.content))
    provider = SparseComparisonProvider()
    ingestion = IngestionService(
        repository,
        provider,
        embedder,
        ResilientArticleTagger(),
    )
    await ingestion.ingest("M&M")
    await ingestion.ingest("TCS")
    await repository.follow_stock("comparison@example.com", "M&M")
    await repository.follow_stock("comparison@example.com", "TCS")
    agent = EquityResearchAgent(
        repository,
        embedder,
        ClaimPreservingAnswerGenerator(DeterministicAnswerGenerator()),
        ingestion,
    )
    result = await agent.chat(
        "comparison@example.com",
        "Compare M&M and TCS latest news",
        scope_tickers=("M&M", "TCS"),
    )

    assert result.grounded is True
    assert result.answer != "I don't have that in the ingested data."
    assert result.citations
    assert all(citation.kind is DocumentKind.FUNDAMENTALS for citation in result.citations)
    assert all("Bharti" not in citation.title for citation in result.citations)
