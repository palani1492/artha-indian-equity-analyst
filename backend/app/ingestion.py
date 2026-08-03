from __future__ import annotations

from app.domain.models import (
    DocumentKind,
    Exchange,
    IngestionResult,
    SourceDocument,
    Stock,
    canonical_source_url,
    normalize_ticker,
    source_story_fingerprint,
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
            previous_stock = await self._repository.get_stock(ticker)
            existing = await self._repository.list_documents(ticker)
            candidates, pre_skipped = self._deduplicate_candidates(
                raw_documents, existing
            )
            documents = await self._tag_documents(candidates)
            sentiment_evidence = tuple(
                document
                for document in (*existing, *documents)
                if document.kind is DocumentKind.NEWS
            )
            rolling_sentiment = self._rolling_sentiment(
                previous_stock or stock, sentiment_evidence
            )
            stock = stock.model_copy(update={"sentiment": rolling_sentiment})
            await self._repository.upsert_stock(stock)
            inserted = 0
            skipped = pre_skipped
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
            await self._repository.deduplicate_documents(ticker)
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

    @staticmethod
    def _deduplicate_candidates(
        candidates: tuple[SourceDocument, ...],
        existing: tuple[SourceDocument, ...],
    ) -> tuple[tuple[SourceDocument, ...], int]:
        existing_hashes = {
            document.content_hash
            for document in existing
            if document.kind is DocumentKind.NEWS
        }
        seen_urls = {
            canonical_source_url(document.url)
            for document in existing
            if document.kind is DocumentKind.NEWS
        }
        seen_stories = {
            source_story_fingerprint(document)
            for document in existing
            if document.kind is DocumentKind.NEWS
        }
        fresh: list[SourceDocument] = []
        skipped = 0
        for document in candidates:
            if document.kind is DocumentKind.FUNDAMENTALS:
                fresh.append(document)
                continue
            canonical_url = canonical_source_url(document.url)
            story = source_story_fingerprint(document)
            if (
                document.content_hash in existing_hashes
                or canonical_url in seen_urls
                or story in seen_stories
            ):
                skipped += 1
                continue
            existing_hashes.add(document.content_hash)
            seen_urls.add(canonical_url)
            seen_stories.add(story)
            fresh.append(document)
        return tuple(fresh), skipped
