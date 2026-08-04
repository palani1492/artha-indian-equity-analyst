from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass

from app.domain.models import (
    DocumentKind,
    InvestorPersona,
    SourceDocument,
    Stock,
    canonical_source_url,
    source_story_fingerprint,
)


@dataclass(frozen=True, slots=True)
class _StoredDocument:
    document: SourceDocument
    embedding: tuple[float, ...]


class InMemoryResearchRepository:
    """Deterministic repository used for tests and zero-infrastructure demos."""

    def __init__(self) -> None:
        self._stocks: dict[str, Stock] = {}
        self._documents: dict[str, _StoredDocument] = {}
        self._hashes: set[tuple[str, str]] = set()
        self._personas: dict[str, InvestorPersona] = {}
        self._persona_embeddings: dict[str, tuple[float, ...]] = {}
        self._follows: dict[str, set[str]] = defaultdict(set)
        self._sessions: dict[str, tuple[str, float]] = {}
        self._users: dict[str, dict[str, str | None]] = {}
        self._ticker_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        return None

    async def healthcheck(self) -> bool:
        return True

    @asynccontextmanager
    async def ticker_lock(self, ticker: str):
        async with self._ticker_locks[ticker]:
            yield

    async def upsert_stock(self, stock: Stock) -> None:
        async with self._write_lock:
            self._stocks = {**self._stocks, stock.ticker: stock}

    async def get_stock(self, ticker: str) -> Stock | None:
        return self._stocks.get(ticker)

    async def follow_stock(self, user_id: str, ticker: str) -> bool:
        async with self._write_lock:
            existed = ticker in self._follows[user_id]
            updated = set(self._follows[user_id])
            updated.add(ticker)
            self._follows[user_id] = updated
            return not existed

    async def unfollow_stock(self, user_id: str, ticker: str) -> bool:
        async with self._write_lock:
            existed = ticker in self._follows.get(user_id, set())
            if not existed:
                return False
            updated = set(self._follows[user_id])
            updated.remove(ticker)
            self._follows = {**self._follows, user_id: updated}
            return True

    async def list_followed_tickers(
        self, user_id: str | None = None
    ) -> tuple[str, ...]:
        if user_id is not None:
            return tuple(sorted(self._follows.get(user_id, set())))
        return tuple(
            sorted(
                {ticker for followed in self._follows.values() for ticker in followed}
            )
        )

    async def list_stocks_for_user(self, user_id: str) -> tuple[Stock, ...]:
        tickers = await self.list_followed_tickers(user_id)
        return tuple(
            self._stocks[ticker] for ticker in tickers if ticker in self._stocks
        )

    async def has_document_hash(self, ticker: str, content_hash: str) -> bool:
        return (ticker, content_hash) in self._hashes

    async def insert_document(
        self, document: SourceDocument, embedding: tuple[float, ...]
    ) -> bool:
        key = (document.ticker, document.content_hash)
        async with self._write_lock:
            matching = [
                stored.document
                for stored in self._documents.values()
                if stored.document.ticker == document.ticker
                and (
                    stored.document.content_hash == document.content_hash
                    or (
                        document.kind is DocumentKind.NEWS
                        and canonical_source_url(stored.document.url)
                        == canonical_source_url(document.url)
                    )
                )
            ]
            if key in self._hashes or matching:
                return False
            self._hashes = {*self._hashes, key}
            self._documents = {
                **self._documents,
                document.id: _StoredDocument(document=document, embedding=embedding),
            }
            return True

    async def upsert_document(
        self, document: SourceDocument, embedding: tuple[float, ...]
    ) -> bool:
        async with self._write_lock:
            matching_ids = [
                document_id
                for document_id, stored in self._documents.items()
                if stored.document.ticker == document.ticker
                and stored.document.kind == document.kind
            ]
            existing_id = matching_ids[0] if matching_ids else None
            if existing_id is None:
                key = (document.ticker, document.content_hash)
                self._hashes = {*self._hashes, key}
                self._documents = {
                    **self._documents,
                    document.id: _StoredDocument(
                        document=document, embedding=embedding
                    ),
                }
                return True
            stale_ids = set(matching_ids[1:])
            self._hashes = {
                key
                for key in self._hashes
                if key[0] != document.ticker
                or all(
                    self._documents[document_id].document.content_hash != key[1]
                    for document_id in matching_ids
                    if document_id in self._documents
                )
            }
            self._hashes = {*self._hashes, (document.ticker, document.content_hash)}
            self._documents = {
                document_id: stored
                for document_id, stored in self._documents.items()
                if document_id not in stale_ids
            }
            self._documents = {
                **self._documents,
                existing_id: _StoredDocument(
                    document=document.model_copy(update={"id": existing_id}),
                    embedding=embedding,
                ),
            }
            return False

    async def count_documents(self, ticker: str) -> int:
        return sum(item.document.ticker == ticker for item in self._documents.values())

    async def list_documents(
        self, ticker: str | None = None
    ) -> tuple[SourceDocument, ...]:
        documents = (
            item.document
            for item in self._documents.values()
            if ticker is None or item.document.ticker == ticker
        )
        return tuple(
            sorted(
                documents, key=lambda item: (item.published_at, item.id), reverse=True
            )
        )

    async def deduplicate_documents(self, ticker: str | None = None) -> int:
        async with self._write_lock:
            candidates = sorted(
                self._documents.items(),
                key=lambda item: (item[1].document.published_at, item[0]),
                reverse=True,
            )
            seen: set[tuple[str, str]] = set()
            seen_news_urls: set[tuple[str, str]] = set()
            seen_news_stories: set[tuple[str, str]] = set()
            stale_ids: set[str] = set()
            for document_id, stored in candidates:
                document = stored.document
                if ticker is not None and document.ticker != ticker:
                    continue
                if document.kind is DocumentKind.NEWS:
                    url_identity = (
                        document.ticker,
                        canonical_source_url(document.url),
                    )
                    story_identity = (
                        document.ticker,
                        source_story_fingerprint(document),
                    )
                    if (
                        url_identity in seen_news_urls
                        or story_identity in seen_news_stories
                    ):
                        stale_ids.add(document_id)
                        continue
                    seen_news_urls.add(url_identity)
                    seen_news_stories.add(story_identity)
                    continue
                identity = (document.ticker, document.kind.value)
                if identity in seen:
                    stale_ids.add(document_id)
                    continue
                seen.add(identity)
            if not stale_ids:
                return 0
            self._documents = {
                document_id: stored
                for document_id, stored in self._documents.items()
                if document_id not in stale_ids
            }
            self._hashes = {
                (stored.document.ticker, stored.document.content_hash)
                for stored in self._documents.values()
            }
            return len(stale_ids)

    async def search_documents(
        self,
        query_embedding: tuple[float, ...],
        *,
        tickers: tuple[str, ...],
        limit: int,
    ) -> tuple[SourceDocument, ...]:
        allowed = set(tickers)
        candidates = (
            item for item in self._documents.values() if item.document.ticker in allowed
        )
        scored = sorted(
            (
                (self._cosine(query_embedding, item.embedding), item.document)
                for item in candidates
            ),
            key=lambda pair: (pair[0], pair[1].published_at, pair[1].id),
            reverse=True,
        )
        return tuple(document for _, document in scored[:limit])

    async def get_persona(self, user_id: str) -> InvestorPersona:
        return self._personas.get(user_id, InvestorPersona(user_id=user_id))

    async def save_persona(
        self, persona: InvestorPersona, embedding: tuple[float, ...]
    ) -> None:
        async with self._write_lock:
            self._personas = {**self._personas, persona.user_id: persona}
            self._persona_embeddings = {
                **self._persona_embeddings,
                persona.user_id: embedding,
            }

    async def create_session(
        self, session_id: str, user_id: str, expires_at: float
    ) -> None:
        async with self._write_lock:
            self._sessions = {**self._sessions, session_id: (user_id, expires_at)}

    async def upsert_user(
        self, user_id: str, email: str, name: str | None, picture: str | None
    ) -> None:
        async with self._write_lock:
            self._users = {
                **self._users,
                user_id: {"email": email, "name": name, "picture": picture},
            }

    async def get_user(self, user_id: str) -> dict[str, str | None] | None:
        user = self._users.get(user_id)
        return {**user, "id": user_id} if user else None

    async def list_users(self) -> tuple[dict[str, str | None], ...]:
        return tuple(
            {**user, "id": user_id}
            for user_id, user in sorted(
                self._users.items(), key=lambda item: (item[1]["email"] or "", item[0])
            )
        )

    async def reset_user_profile(self, user_id: str) -> bool:
        if user_id not in self._users:
            return False
        async with self._write_lock:
            self._personas = {
                key: persona for key, persona in self._personas.items() if key != user_id
            }
            self._persona_embeddings = {
                key: embedding
                for key, embedding in self._persona_embeddings.items()
                if key != user_id
            }
            self._follows = {
                key: tickers for key, tickers in self._follows.items() if key != user_id
            }
        return True

    async def get_session_user(self, session_id: str, now: float) -> str | None:
        session = self._sessions.get(session_id)
        if session is None or session[1] <= now:
            return None
        return session[0]

    async def delete_session(self, session_id: str) -> None:
        async with self._write_lock:
            self._sessions = {
                key: value for key, value in self._sessions.items() if key != session_id
            }

    @staticmethod
    def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        numerator = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0
