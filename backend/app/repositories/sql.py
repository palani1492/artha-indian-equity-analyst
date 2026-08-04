from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    delete,
    select,
    text,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.models import (
    ConversationMessage,
    DocumentKind,
    GraphFact,
    InvestorPersona,
    ResearchConversation,
    ResearchNote,
    SourceDocument,
    Stock,
    canonical_source_url,
    source_story_fingerprint,
)


class Base(DeclarativeBase):
    pass


class StockRow(Base):
    __tablename__ = "stocks"
    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(3), nullable=False)
    bse_id: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    sector: Mapped[str] = mapped_column(String(80), nullable=False)
    price_inr: Mapped[Any] = mapped_column(Numeric(20, 4), nullable=False)
    market_cap_crore: Mapped[Any | None] = mapped_column(Numeric(24, 4))
    pe_ratio: Mapped[Any | None] = mapped_column(Numeric(16, 4))
    debt_to_equity: Mapped[Any | None] = mapped_column(Numeric(16, 4))
    dividend_yield: Mapped[Any | None] = mapped_column(Numeric(16, 4))
    roe: Mapped[Any | None] = mapped_column(Numeric(16, 4))
    revenue_growth: Mapped[Any | None] = mapped_column(Numeric(16, 4))
    sentiment: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    change_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class DocumentRow(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("ticker", "content_hash", name="uq_documents_ticker_hash"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ticker: Mapped[str] = mapped_column(
        ForeignKey("stocks.ticker", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sentiment: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    impact: Mapped[str] = mapped_column(String(40), nullable=False)
    event_tag: Mapped[str] = mapped_column(String(80), nullable=False)
    mentioned_tickers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)


class GraphFactRow(Base):
    __tablename__ = "graph_facts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    predicate: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    object_value: Mapped[str | None] = mapped_column(String(160))
    source_document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(String(500), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class PersonaRow(Base):
    __tablename__ = "personas"
    user_id: Mapped[str] = mapped_column(String(320), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class FollowRow(Base):
    __tablename__ = "stock_follows"
    user_id: Mapped[str] = mapped_column(String(320), primary_key=True)
    ticker: Mapped[str] = mapped_column(
        ForeignKey("stocks.ticker", ondelete="CASCADE"), primary_key=True
    )


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(320), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(160))
    picture: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[float] = mapped_column(Float, nullable=False, index=True)


class ConversationRow(Base):
    __tablename__ = "research_conversations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationMessageRow(Base):
    __tablename__ = "research_messages"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("research_conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    scope_tickers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NoteRow(Base):
    __tablename__ = "research_notes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    scope_tickers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SqlAlchemyResearchRepository:
    def __init__(self, database_url: str) -> None:
        normalized_url = database_url.replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )
        self.engine: AsyncEngine = create_async_engine(
            normalized_url, pool_pre_ping=True
        )
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self._local_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def initialize(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            if self.engine.dialect.name == "postgresql":
                vector_installed = await connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
                    )
                )
                documents_table = await connection.scalar(
                    text("SELECT to_regclass('public.documents') IS NOT NULL")
                )
                if not vector_installed or not documents_table:
                    raise RuntimeError(
                        "Database migrations or pgvector extension are missing"
                    )

    async def healthcheck(self) -> bool:
        try:
            await self.initialize()
            return True
        except (SQLAlchemyError, OSError, RuntimeError):
            return False

    @asynccontextmanager
    async def ticker_lock(self, ticker: str):
        if self.engine.dialect.name != "postgresql":
            async with self._local_locks[ticker]:
                yield
            return
        async with self.engine.connect() as connection:
            await connection.execute(
                text("SELECT pg_advisory_lock(hashtext(:ticker))"), {"ticker": ticker}
            )
            try:
                yield
            finally:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:ticker))"),
                    {"ticker": ticker},
                )

    async def upsert_stock(self, stock: Stock) -> None:
        values = stock.model_dump(mode="python")
        values["exchange"] = stock.exchange.value
        async with self._sessions.begin() as session:
            row = await session.get(StockRow, stock.ticker)
            if row is None:
                session.add(StockRow(**values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    async def get_stock(self, ticker: str) -> Stock | None:
        async with self._sessions() as session:
            row = await session.get(StockRow, ticker)
            return self._stock(row) if row else None

    async def follow_stock(self, user_id: str, ticker: str) -> bool:
        async with self._sessions.begin() as session:
            existing = await session.get(
                FollowRow, {"user_id": user_id, "ticker": ticker}
            )
            if existing:
                return False
            session.add(FollowRow(user_id=user_id, ticker=ticker))
            return True

    async def unfollow_stock(self, user_id: str, ticker: str) -> bool:
        async with self._sessions.begin() as session:
            existing = await session.get(
                FollowRow, {"user_id": user_id, "ticker": ticker}
            )
            if existing is None:
                return False
            await session.delete(existing)
            return True

    async def list_followed_tickers(
        self, user_id: str | None = None
    ) -> tuple[str, ...]:
        query = select(FollowRow.ticker).distinct().order_by(FollowRow.ticker)
        if user_id is not None:
            query = query.where(FollowRow.user_id == user_id)
        async with self._sessions() as session:
            return tuple((await session.scalars(query)).all())

    async def list_stocks_for_user(self, user_id: str) -> tuple[Stock, ...]:
        query = (
            select(StockRow)
            .join(FollowRow, FollowRow.ticker == StockRow.ticker)
            .where(FollowRow.user_id == user_id)
            .order_by(StockRow.ticker)
        )
        async with self._sessions() as session:
            return tuple(
                self._stock(row) for row in (await session.scalars(query)).all()
            )

    async def has_document_hash(self, ticker: str, content_hash: str) -> bool:
        query = (
            select(DocumentRow.id)
            .where(
                DocumentRow.ticker == ticker, DocumentRow.content_hash == content_hash
            )
            .limit(1)
        )
        async with self._sessions() as session:
            return (await session.scalar(query)) is not None

    async def insert_document(
        self, document: SourceDocument, embedding: tuple[float, ...]
    ) -> bool:
        values = document.model_dump(mode="python")
        values.update(
            kind=document.kind.value, url=str(document.url), embedding=list(embedding)
        )
        async with self._sessions.begin() as session:
            duplicate_query = select(DocumentRow).where(
                DocumentRow.ticker == document.ticker,
                (
                    (DocumentRow.content_hash == document.content_hash)
                    | (
                        (DocumentRow.kind == DocumentKind.NEWS.value)
                        & (DocumentRow.url == str(document.url))
                    )
                ),
            )
            if await session.scalar(duplicate_query) is not None:
                return False
            session.add(DocumentRow(**values))
        return True

    async def upsert_document(
        self, document: SourceDocument, embedding: tuple[float, ...]
    ) -> bool:
        values = document.model_dump(mode="python")
        values.update(
            kind=document.kind.value, url=str(document.url), embedding=list(embedding)
        )
        query = (
            select(DocumentRow)
            .where(
                DocumentRow.ticker == document.ticker,
                DocumentRow.kind == document.kind.value,
            )
            .order_by(DocumentRow.published_at.desc())
        )
        async with self._sessions.begin() as session:
            rows = list((await session.scalars(query)).all())
            row = rows[0] if rows else None
            if row is None:
                session.add(DocumentRow(**values))
                return True
            for stale in rows[1:]:
                await session.delete(stale)
            for key, value in values.items():
                if key != "id":
                    setattr(row, key, value)
            return False

    async def count_documents(self, ticker: str) -> int:
        query = select(DocumentRow.id).where(DocumentRow.ticker == ticker)
        async with self._sessions() as session:
            return len((await session.scalars(query)).all())

    async def list_documents(
        self, ticker: str | None = None
    ) -> tuple[SourceDocument, ...]:
        query = select(DocumentRow).order_by(
            DocumentRow.published_at.desc(), DocumentRow.id
        )
        if ticker is not None:
            query = query.where(DocumentRow.ticker == ticker)
        async with self._sessions() as session:
            return tuple(
                self._document(row) for row in (await session.scalars(query)).all()
            )

    async def deduplicate_documents(self, ticker: str | None = None) -> int:
        query = select(DocumentRow).order_by(
            DocumentRow.published_at.desc(), DocumentRow.id.desc()
        )
        if ticker is not None:
            query = query.where(DocumentRow.ticker == ticker)
        async with self._sessions.begin() as session:
            rows = list((await session.scalars(query)).all())
            seen: set[tuple[str, str]] = set()
            seen_news_urls: set[tuple[str, str]] = set()
            seen_news_stories: set[tuple[str, str]] = set()
            stale: list[DocumentRow] = []
            for row in rows:
                if row.kind == DocumentKind.NEWS.value:
                    document = self._document(row)
                    url_identity = (row.ticker, canonical_source_url(row.url))
                    story_identity = (row.ticker, source_story_fingerprint(document))
                    if (
                        url_identity in seen_news_urls
                        or story_identity in seen_news_stories
                    ):
                        stale.append(row)
                        continue
                    seen_news_urls.add(url_identity)
                    seen_news_stories.add(story_identity)
                    continue
                identity = (row.ticker, row.kind)
                if identity in seen:
                    stale.append(row)
                else:
                    seen.add(identity)
            for row in stale:
                await session.delete(row)
            return len(stale)

    async def upsert_graph_facts(self, facts: tuple[GraphFact, ...]) -> None:
        async with self._sessions.begin() as session:
            for fact in facts:
                values = fact.model_dump(mode="python")
                values["source_url"] = str(fact.source_url)
                row = await session.get(GraphFactRow, fact.id)
                if row is None:
                    session.add(GraphFactRow(**values))
                    continue
                for key, value in values.items():
                    setattr(row, key, value)

    async def list_graph_facts(self, ticker: str) -> tuple[GraphFact, ...]:
        query = (
            select(GraphFactRow)
            .join(DocumentRow, DocumentRow.id == GraphFactRow.source_document_id)
            .where(
                (GraphFactRow.subject_id == ticker)
                | (GraphFactRow.object_id == ticker)
                | (DocumentRow.ticker == ticker)
            )
            .order_by(GraphFactRow.observed_at.desc(), GraphFactRow.id)
        )
        async with self._sessions() as session:
            return tuple(
                self._graph_fact(row) for row in (await session.scalars(query)).all()
            )

    async def search_documents(
        self,
        query_embedding: tuple[float, ...],
        *,
        tickers: tuple[str, ...],
        limit: int,
    ) -> tuple[SourceDocument, ...]:
        if not tickers:
            return ()
        if self.engine.dialect.name == "postgresql":
            query = (
                select(DocumentRow)
                .where(DocumentRow.ticker.in_(tickers))
                .order_by(DocumentRow.embedding.cosine_distance(list(query_embedding)))
                .limit(limit)
            )
            async with self._sessions() as session:
                return tuple(
                    self._document(row) for row in (await session.scalars(query)).all()
                )
        query = select(DocumentRow).where(DocumentRow.ticker.in_(tickers))
        async with self._sessions() as session:
            documents = tuple((await session.scalars(query)).all())
        scored = sorted(
            (
                (
                    self._cosine(query_embedding, tuple(row.embedding)),
                    self._document(row),
                )
                for row in documents
                if row.ticker in tickers
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        return tuple(document for _, document in scored[:limit])

    async def get_persona(self, user_id: str) -> InvestorPersona:
        async with self._sessions() as session:
            row = await session.get(PersonaRow, user_id)
            return (
                InvestorPersona.model_validate(row.data)
                if row
                else InvestorPersona(user_id=user_id)
            )

    async def save_persona(
        self, persona: InvestorPersona, embedding: tuple[float, ...]
    ) -> None:
        payload = persona.model_dump(mode="json")
        async with self._sessions.begin() as session:
            row = await session.get(PersonaRow, persona.user_id)
            values = {
                "data": payload,
                "embedding": list(embedding),
                "version": persona.version,
                "updated_at": persona.updated_at,
            }
            if row is None:
                session.add(PersonaRow(user_id=persona.user_id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    async def upsert_user(
        self, user_id: str, email: str, name: str | None, picture: str | None
    ) -> None:
        async with self._sessions.begin() as session:
            row = await session.get(UserRow, user_id)
            if row is None:
                session.add(
                    UserRow(id=user_id, email=email, name=name, picture=picture)
                )
            else:
                row.email, row.name, row.picture = email, name, picture

    async def get_user(self, user_id: str) -> dict[str, str | None] | None:
        async with self._sessions() as session:
            row = await session.get(UserRow, user_id)
            if row is None:
                return None
            return {
                "id": row.id,
                "email": row.email,
                "name": row.name,
                "picture": row.picture,
            }

    async def list_users(self) -> tuple[dict[str, str | None], ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(select(UserRow).order_by(UserRow.email, UserRow.id))
            ).all()
            return tuple(
                {
                    "id": row.id,
                    "email": row.email,
                    "name": row.name,
                    "picture": row.picture,
                }
                for row in rows
            )

    async def reset_user_profile(self, user_id: str) -> bool:
        async with self._sessions.begin() as session:
            user = await session.get(UserRow, user_id)
            if user is None:
                return False
            await session.execute(delete(PersonaRow).where(PersonaRow.user_id == user_id))
            await session.execute(delete(FollowRow).where(FollowRow.user_id == user_id))
            return True

    async def reset_user_follows(self, user_id: str) -> bool:
        async with self._sessions.begin() as session:
            user = await session.get(UserRow, user_id)
            if user is None:
                return False
            await session.execute(delete(FollowRow).where(FollowRow.user_id == user_id))
            return True

    async def delete_user_conversations(self, user_id: str) -> bool:
        async with self._sessions.begin() as session:
            user = await session.get(UserRow, user_id)
            if user is None:
                return False
            conversation_ids = select(ConversationRow.id).where(
                ConversationRow.user_id == user_id
            )
            await session.execute(
                delete(ConversationMessageRow).where(
                    ConversationMessageRow.conversation_id.in_(conversation_ids)
                )
            )
            await session.execute(delete(ConversationRow).where(ConversationRow.user_id == user_id))
            return True

    async def create_session(
        self, session_id: str, user_id: str, expires_at: float
    ) -> None:
        async with self._sessions.begin() as session:
            session.add(
                SessionRow(id=session_id, user_id=user_id, expires_at=expires_at)
            )

    async def get_session_user(self, session_id: str, now: float) -> str | None:
        async with self._sessions() as session:
            row = await session.get(SessionRow, session_id)
            return row.user_id if row and row.expires_at > now else None

    async def delete_session(self, session_id: str) -> None:
        async with self._sessions.begin() as session:
            await session.execute(delete(SessionRow).where(SessionRow.id == session_id))

    async def create_conversation(self, conversation: ResearchConversation) -> None:
        async with self._sessions.begin() as session:
            session.add(ConversationRow(**conversation.model_dump(mode="python")))

    async def list_conversations(self, user_id: str) -> tuple[ResearchConversation, ...]:
        query = (
            select(ConversationRow)
            .where(ConversationRow.user_id == user_id)
            .order_by(ConversationRow.updated_at.desc(), ConversationRow.id)
        )
        async with self._sessions() as session:
            return tuple(
                self._conversation(row) for row in (await session.scalars(query)).all()
            )

    async def get_conversation(
        self, user_id: str, conversation_id: str
    ) -> ResearchConversation | None:
        query = select(ConversationRow).where(
            ConversationRow.id == conversation_id, ConversationRow.user_id == user_id
        )
        async with self._sessions() as session:
            row = await session.scalar(query)
            return self._conversation(row) if row else None

    async def update_conversation(self, conversation: ResearchConversation) -> None:
        async with self._sessions.begin() as session:
            row = await session.get(ConversationRow, conversation.id)
            if row is None or row.user_id != conversation.user_id:
                return
            row.title = conversation.title
            row.updated_at = conversation.updated_at

    async def add_conversation_message(self, message: ConversationMessage) -> None:
        async with self._sessions.begin() as session:
            values = message.model_dump(mode="python")
            values["citations"] = [
                citation.model_dump(mode="json") for citation in message.citations
            ]
            session.add(ConversationMessageRow(**values))
            conversation = await session.get(ConversationRow, message.conversation_id)
            if conversation:
                conversation.updated_at = message.created_at

    async def list_conversation_messages(
        self, user_id: str, conversation_id: str
    ) -> tuple[ConversationMessage, ...]:
        query = (
            select(ConversationMessageRow)
            .join(
                ConversationRow,
                ConversationRow.id == ConversationMessageRow.conversation_id,
            )
            .where(
                ConversationRow.id == conversation_id,
                ConversationRow.user_id == user_id,
            )
            .order_by(ConversationMessageRow.created_at, ConversationMessageRow.id)
        )
        async with self._sessions() as session:
            return tuple(
                self._message(row) for row in (await session.scalars(query)).all()
            )

    async def create_note(self, note: ResearchNote) -> None:
        async with self._sessions.begin() as session:
            session.add(self._note_row(note))

    async def list_notes(self, user_id: str) -> tuple[ResearchNote, ...]:
        query = select(NoteRow).where(NoteRow.user_id == user_id).order_by(
            NoteRow.updated_at.desc(), NoteRow.id
        )
        async with self._sessions() as session:
            return tuple(self._note(row) for row in (await session.scalars(query)).all())

    async def get_note(self, user_id: str, note_id: str) -> ResearchNote | None:
        query = select(NoteRow).where(NoteRow.id == note_id, NoteRow.user_id == user_id)
        async with self._sessions() as session:
            row = await session.scalar(query)
            return self._note(row) if row else None

    async def update_note(self, note: ResearchNote) -> None:
        async with self._sessions.begin() as session:
            row = await session.get(NoteRow, note.id)
            if row is None or row.user_id != note.user_id:
                return
            values = note.model_dump(mode="python")
            values["citations"] = [
                citation.model_dump(mode="json") for citation in note.citations
            ]
            for key in ("title", "body", "scope_tickers", "citations", "updated_at"):
                setattr(row, key, values[key])

    async def delete_note(self, user_id: str, note_id: str) -> bool:
        async with self._sessions.begin() as session:
            row = await session.get(NoteRow, note_id)
            if row is None or row.user_id != user_id:
                return False
            await session.delete(row)
            return True

    @staticmethod
    def _stock(row: StockRow) -> Stock:
        return Stock.model_validate(
            {
                column.name: getattr(row, column.name)
                for column in StockRow.__table__.columns
            }
        )

    @staticmethod
    def _document(row: DocumentRow) -> SourceDocument:
        values = {
            column.name: getattr(row, column.name)
            for column in DocumentRow.__table__.columns
            if column.name != "embedding"
        }
        return SourceDocument.model_validate(values)

    @staticmethod
    def _graph_fact(row: GraphFactRow) -> GraphFact:
        return GraphFact.model_validate(
            {
                column.name: getattr(row, column.name)
                for column in GraphFactRow.__table__.columns
            }
        )

    @staticmethod
    def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        numerator = sum(a * b for a, b in zip(left, right, strict=False))
        denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(
            sum(b * b for b in right)
        )
        return numerator / denominator if denominator else 0.0

    @staticmethod
    def _conversation(row: ConversationRow) -> ResearchConversation:
        return ResearchConversation.model_validate(
            {
                column.name: getattr(row, column.name)
                for column in ConversationRow.__table__.columns
            }
        )

    @staticmethod
    def _message(row: ConversationMessageRow) -> ConversationMessage:
        return ConversationMessage.model_validate(
            {
                column.name: getattr(row, column.name)
                for column in ConversationMessageRow.__table__.columns
            }
        )

    @staticmethod
    def _note_row(note: ResearchNote) -> NoteRow:
        values = note.model_dump(mode="python")
        values["citations"] = [
            citation.model_dump(mode="json") for citation in note.citations
        ]
        return NoteRow(**values)

    @staticmethod
    def _note(row: NoteRow) -> ResearchNote:
        return ResearchNote.model_validate(
            {column.name: getattr(row, column.name) for column in NoteRow.__table__.columns}
        )
