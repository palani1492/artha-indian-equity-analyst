from __future__ import annotations

import json
import re
from typing import Protocol

from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import SourceDocument

UPPERCASE_TICKER = re.compile(r"\b[A-Z][A-Z0-9&.-]{1,19}\b")


class ArticleTags(BaseModel):
    model_config = ConfigDict(frozen=True)

    mentioned_tickers: tuple[str, ...]
    sentiment: float = Field(ge=-1, le=1)
    impact: str
    event_tag: str


class ArticleTagger(Protocol):
    async def tag(self, document: SourceDocument) -> ArticleTags: ...


class LexicalArticleTagger:
    async def tag(self, document: SourceDocument) -> ArticleTags:
        text = f"{document.title} {document.content}"
        normalized = text.lower()
        positive = sum(
            token in normalized
            for token in ("profit", "growth", "beat", "upgrade", "wins", "positive")
        )
        negative = sum(
            token in normalized
            for token in ("loss", "debt", "downgrade", "probe", "falls", "negative")
        )
        inferred = max(-1.0, min(1.0, (positive - negative) / 3))
        sentiment = document.sentiment if document.sentiment else inferred
        event = next(
            (
                event
                for keyword, event in (
                    ("earnings", "earnings"),
                    ("dividend", "dividend"),
                    ("acquisition", "m&a"),
                    ("order", "order-win"),
                    ("debt", "balance-sheet"),
                )
                if keyword in normalized
            ),
            document.event_tag or "general",
        )
        tickers = {document.ticker, *UPPERCASE_TICKER.findall(text)}
        impact = (
            document.impact
            if document.impact != "neutral"
            else ("high" if abs(sentiment) >= 0.5 else "medium")
        )
        return ArticleTags(
            mentioned_tickers=tuple(sorted(tickers)),
            sentiment=sentiment,
            impact=impact,
            event_tag=event,
        )


class OpenAIArticleTagger:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def tag(self, document: SourceDocument) -> ArticleTags:
        response = await self._client.responses.create(
            model=self._model,
            input=(
                "Extract Indian equity article tags as JSON with mentioned_tickers (array), "
                "sentiment (-1 to 1), impact (low/medium/high), and event_tag.\n"
                f"Ticker context: {document.ticker}\nArticle: {document.title}\n{document.content}"
            ),
            temperature=0,
        )
        return ArticleTags.model_validate(json.loads(response.output_text))


class ResilientArticleTagger:
    def __init__(self, primary: ArticleTagger | None = None) -> None:
        self._primary = primary
        self._fallback = LexicalArticleTagger()
        self._cache: dict[str, ArticleTags] = {}

    async def tag(self, document: SourceDocument) -> ArticleTags:
        if document.content_hash in self._cache:
            return self._cache[document.content_hash]
        tags = await self._tag_uncached(document)
        self._cache = {**self._cache, document.content_hash: tags}
        return tags

    async def _tag_uncached(self, document: SourceDocument) -> ArticleTags:
        if self._primary is not None:
            try:
                return await self._primary.tag(document)
            except (OpenAIError, RuntimeError, TimeoutError, ValueError):
                return await self._fallback.tag(document)
        return await self._fallback.tag(document)
