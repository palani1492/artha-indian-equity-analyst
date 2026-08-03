from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
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
            sentiment=sentiment,
            impact=impact,
            event_tag=event_tag,
            mentioned_tickers=mentioned_tickers,
        )


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=1)
    document_id: str
    title: str
    url: HttpUrl


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
    debug: dict[str, Any] = Field(default_factory=dict, exclude=True)
