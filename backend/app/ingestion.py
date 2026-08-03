from __future__ import annotations

from app.domain.models import (
    DocumentKind,
    Exchange,
    IngestionResult,
    SourceDocument,
    Stock,
    normalize_ticker,
)
from app.embeddings import Embedder
from app.providers import MarketDataProvider
from app.repositories.base import ResearchRepository
from app.tagging import ArticleTagger


class IngestionService:
    def __init__(
        self,
        repository: ResearchRepository,
        provider: MarketDataProvider,
        embedder: Embedder,
        tagger: ArticleTagger,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._embedder = embedder
        self._tagger = tagger

    async def ingest(self, raw_ticker: str) -> IngestionResult:
        ticker, exchange = normalize_ticker(raw_ticker)
        async with self._repository.ticker_lock(ticker):
            provider_ticker = f"{ticker}.BO" if exchange is Exchange.BSE else ticker
            stock, raw_documents = await self._provider.fetch(provider_ticker)
            documents = await self._tag_documents(raw_documents)
            rolling_sentiment = self._rolling_sentiment(stock, documents)
            stock = stock.model_copy(update={"sentiment": rolling_sentiment})
            await self._repository.upsert_stock(stock)
            inserted = 0
            skipped = 0
            for document in documents:
                if document.kind.value == "fundamentals":
                    embedding = await self._embedder.embed(document.content)
                    if await self._repository.upsert_document(document, embedding):
                        inserted += 1
                    else:
                        skipped += 1
                    continue
                if await self._repository.has_document_hash(
                    ticker, document.content_hash
                ):
                    skipped += 1
                    continue
                embedding = await self._embedder.embed(document.content)
                if await self._repository.insert_document(document, embedding):
                    inserted += 1
                else:
                    skipped += 1
            return IngestionResult(
                ticker=ticker,
                inserted=inserted,
                skipped=skipped,
                sentiment=rolling_sentiment,
            )

    @staticmethod
    def _rolling_sentiment(stock: Stock, documents: tuple) -> float:
        news_scores = [
            document.sentiment for document in documents if document.kind == "news"
        ]
        if not news_scores:
            return stock.sentiment
        return max(-1.0, min(1.0, sum(news_scores) / len(news_scores)))

    async def _tag_documents(
        self, documents: tuple[SourceDocument, ...]
    ) -> tuple[SourceDocument, ...]:
        tagged: list[SourceDocument] = []
        for document in documents:
            if document.kind is not DocumentKind.NEWS:
                tagged.append(document)
                continue
            tags = await self._tagger.tag(document)
            tagged.append(
                document.model_copy(
                    update={
                        "sentiment": tags.sentiment,
                        "impact": tags.impact,
                        "event_tag": tags.event_tag,
                        "mentioned_tickers": tags.mentioned_tickers,
                    }
                )
            )
        return tuple(tagged)
