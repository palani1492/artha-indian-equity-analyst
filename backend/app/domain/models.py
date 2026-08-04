from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9&.-]{0,19}$")
TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
}


def canonical_source_url(url: str | object) -> str:
    parts = urlsplit(str(url).strip())
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query)
            if key.lower() not in TRACKING_QUERY_KEYS
        )
    )
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, "")
    )


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"


class DocumentKind(StrEnum):
    FUNDAMENTALS = "fundamentals"
    NEWS = "news"


class SourceTier(StrEnum):
    PRIMARY = "primary"
    COMPANY = "company"
    SECONDARY = "secondary"
    CONTEXTUAL = "contextual"


class RiskTolerance(StrEnum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


def normalize_ticker(raw_ticker: str) -> tuple[str, Exchange]:
    candidate = raw_ticker.strip().upper()
    exchange = Exchange.NSE
    for suffix, suffix_exchange in (
        (".NS", Exchange.NSE),
        (".NSE", Exchange.NSE),
        (".BO", Exchange.BSE),
        (".BSE", Exchange.BSE),
    ):
        if candidate.endswith(suffix):
            candidate = candidate[: -len(suffix)]
            exchange = suffix_exchange
            break
    if not TICKER_PATTERN.fullmatch(candidate):
        raise ValueError("ticker must contain 1-20 valid NSE/BSE symbol characters")
    return candidate, exchange


class Stock(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    exchange: Exchange = Exchange.NSE
    bse_id: str | None = None
    name: str = Field(min_length=1, max_length=160)
    sector: str = Field(default="Other", min_length=1, max_length=80)
    price_inr: Decimal = Field(ge=0)
    market_cap_crore: Decimal | None = Field(default=None, ge=0)
    pe_ratio: Decimal | None = Field(default=None, ge=0)
    debt_to_equity: Decimal | None = Field(default=None, ge=0)
    dividend_yield: Decimal | None = Field(default=None, ge=0)
    roe: Decimal | None = None
    revenue_growth: Decimal | None = None
    sentiment: float = Field(default=0.0, ge=-1.0, le=1.0)
    change_pct: float = Field(default=0.0, ge=-100.0, le=100.0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        ticker, _ = normalize_ticker(value)
        return ticker


def normalize_company_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def safe_company_aliases(stock: Stock) -> tuple[str, ...]:
    normalized_name = normalize_company_text(stock.name)
    shortened_name = normalized_name
    for suffix in (" limited", " ltd", " plc"):
        shortened_name = shortened_name.removesuffix(suffix)
    words = shortened_name.split()
    aliases = {
        normalize_company_text(stock.ticker),
        shortened_name,
        " ".join(words[:2]) if len(words) >= 2 else shortened_name,
    }
    return tuple(sorted((alias for alias in aliases if len(alias) >= 3), key=len, reverse=True))


class InvestorPersona(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=320)
    risk_tolerance: RiskTolerance = RiskTolerance.BALANCED
    style: str = Field(default="Quality at a fair price", max_length=120)
    dividend_focused: bool = False
    avoid_high_debt: bool = False
    max_debt_to_equity: Decimal = Field(default=Decimal(2), ge=0, le=20)
    preferred_sectors: tuple[str, ...] = ()
    excluded_sectors: tuple[str, ...] = ()
    priorities: tuple[str, ...] = (
        "Durable cash flows",
        "Low leverage",
        "Governance",
    )
    avoid: tuple[str, ...] = ("High debt", "Uncited momentum calls")
    horizon: str = Field(default="medium-term", max_length=80)
    notes: tuple[str, ...] = ()
    version: int = Field(default=1, ge=1)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SourceDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    ticker: str
    kind: DocumentKind
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl
    content: str = Field(min_length=1)
    published_at: datetime
    content_hash: str
    source_tier: SourceTier = SourceTier.SECONDARY
    sentiment: float = Field(default=0.0, ge=-1, le=1)
    impact: str = Field(default="neutral", max_length=40)
    event_tag: str = Field(default="general", max_length=80)
    mentioned_tickers: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        ticker: str,
        kind: DocumentKind,
        title: str,
        url: str,
        content: str,
        published_at: datetime,
        source_tier: SourceTier = SourceTier.SECONDARY,
        sentiment: float = 0.0,
        impact: str = "neutral",
        event_tag: str = "general",
        mentioned_tickers: tuple[str, ...] = (),
        dedupe_key: str | None = None,
    ) -> SourceDocument:
        normalized_ticker, _ = normalize_ticker(ticker)
        normalized_content = " ".join(content.split())
        # Content-addressing deduplicates syndicated copies; stable keys can keep
        # one mutable snapshot such as live fundamentals per ticker.
        content_hash = hashlib.sha256(
            (dedupe_key or normalized_content).encode()
        ).hexdigest()
        return cls(
            id=hashlib.sha256(
                f"{normalized_ticker}:{content_hash}".encode()
            ).hexdigest()[:32],
            ticker=normalized_ticker,
            kind=kind,
            title=title.strip(),
            url=HttpUrl(url),
            content=normalized_content,
            published_at=published_at,
            content_hash=content_hash,
            source_tier=source_tier,
            sentiment=sentiment,
            impact=impact,
            event_tag=event_tag,
            mentioned_tickers=mentioned_tickers,
        )


class GraphFact(BaseModel):
    """A deterministic, source-backed edge or observation in the knowledge graph."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=64)
    subject_type: str = Field(min_length=1, max_length=40)
    subject_id: str = Field(min_length=1, max_length=160)
    predicate: str = Field(min_length=1, max_length=80)
    object_type: str = Field(min_length=1, max_length=40)
    object_id: str = Field(min_length=1, max_length=160)
    object_value: str | None = Field(default=None, max_length=160)
    source_document_id: str = Field(min_length=1, max_length=32)
    source_url: HttpUrl
    evidence: str = Field(min_length=1, max_length=500)
    observed_at: datetime


def source_story_fingerprint(document: SourceDocument) -> str:
    """Return a stable content fingerprint for cross-feed news deduplication."""
    normalized_title = " ".join(document.title.lower().split())
    identity_text = normalized_title or " ".join(document.content.lower().split())[:240]
    published_day = document.published_at.astimezone(UTC).date().isoformat()
    normalized = f"{identity_text}|{published_day}"
    return hashlib.sha256(normalized.encode()).hexdigest()


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=1)
    document_id: str
    title: str
    url: HttpUrl
    ticker: str | None = None
    kind: DocumentKind | None = None
    source_tier: SourceTier = SourceTier.SECONDARY
    content: str | None = None
    published_at: datetime | None = None


class ResearchConversation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=320)
    title: str = Field(min_length=1, max_length=200)
    created_at: datetime
    updated_at: datetime


class ConversationMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=64)
    conversation_id: str = Field(min_length=1, max_length=64)
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=12000)
    title: str | None = Field(default=None, max_length=200)
    scope_tickers: tuple[str, ...] = Field(default=(), max_length=10)
    citations: tuple[Citation, ...] = Field(default=(), max_length=20)
    created_at: datetime

    @field_validator("text", "title")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text cannot be blank")
        return cleaned

    @field_validator("scope_tickers")
    @classmethod
    def clean_scope(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(normalize_ticker(value)[0] for value in values))


class ResearchNote(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=320)
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=4000)
    scope_tickers: tuple[str, ...] = Field(default=(), max_length=10)
    citations: tuple[Citation, ...] = Field(default=(), max_length=20)
    created_at: datetime
    updated_at: datetime

    @field_validator("title", "body")
    @classmethod
    def clean_note_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("note text cannot be blank")
        return cleaned

    @field_validator("scope_tickers")
    @classmethod
    def clean_note_scope(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(normalize_ticker(value)[0] for value in values))


class RankedStock(BaseModel):
    model_config = ConfigDict(frozen=True)

    stock: Stock
    score: float
    reasons: tuple[str, ...]


class IngestionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    inserted: int = Field(ge=0)
    skipped: int = Field(ge=0)
    sentiment: float = Field(ge=-1, le=1)


class GroundingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str
    citations: tuple[Citation, ...] = ()
    is_grounded: bool
    violations: tuple[str, ...] = ()


class ChatResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str
    citations: tuple[Citation, ...] = ()
    grounded: bool
    persona_updated: bool = False
    recommendations: tuple[RankedStock, ...] = ()
    title: str | None = None
    answer_kind: str = "research"
    metadata: dict[str, Any] = Field(default_factory=dict)
    persona: InvestorPersona | None = None
    conversation_id: str | None = None
    debug: dict[str, Any] = Field(default_factory=dict, exclude=True)
