from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.domain.models import (
    ChatResult,
    Citation,
    DocumentKind,
    RankedStock,
    SourceDocument,
)
from app.embeddings import Embedder
from app.generation import AnswerGenerator
from app.grounding import GroundingGuard
from app.persona import PersonaExtractor, persona_as_text
from app.ranking import StockRanker
from app.repositories.base import ResearchRepository


class AgentState(TypedDict, total=False):
    user_id: str
    message: str
    ticker: str | None
    persona_updated: bool
    is_recommendation: bool
    is_recent: bool
    recommendations: tuple[RankedStock, ...]
    sources: tuple[SourceDocument, ...]
    citations: tuple[Citation, ...]
    draft: str
    result: ChatResult


class EquityResearchAgent:
    """A compact LangGraph workflow: memory -> retrieve/rank -> compose -> guard."""

    def __init__(
        self,
        repository: ResearchRepository,
        embedder: Embedder,
        generator: AnswerGenerator,
        retrieval_limit: int = 6,
    ) -> None:
        self._repository = repository
        self._embedder = embedder
        self._generator = generator
        self._retrieval_limit = retrieval_limit
        self._persona = PersonaExtractor()
        self._ranker = StockRanker()
        self._guard = GroundingGuard()
        graph = StateGraph(AgentState)
        graph.add_node("memory", self._memory_node)
        graph.add_node("retrieve", self._retrieve_node)
        graph.add_node("compose", self._compose_node)
        graph.add_node("guard", self._guard_node)
        graph.add_edge(START, "memory")
        graph.add_edge("memory", "retrieve")
        graph.add_edge("retrieve", "compose")
        graph.add_edge("compose", "guard")
        graph.add_edge("guard", END)
        self._graph = graph.compile()

    async def chat(
        self, user_id: str, message: str, ticker: str | None = None
    ) -> ChatResult:
        state = await self._graph.ainvoke(
            {"user_id": user_id, "message": message, "ticker": ticker}
        )
        return state["result"]

    async def _memory_node(self, state: AgentState) -> dict[str, Any]:
        persona = await self._repository.get_persona(state["user_id"])
        updated, changed = self._persona.update(persona, state["message"])
        if changed:
            embedding = await self._embedder.embed(persona_as_text(updated))
            await self._repository.save_persona(updated, embedding)
        recommendation = any(
            word in state["message"].lower()
            for word in (
                "recommend",
                "what should i buy",
                "picks",
                "ideas for my profile",
                "best fits my profile",
                "best fit for my profile",
                "which followed",
                "compare",
            )
        )
        recent = any(
            phrase in state["message"].lower()
            for phrase in ("what changed", "this week", "latest", "recent", "news", "update")
        )
        return {
            "persona_updated": changed,
            "is_recommendation": recommendation,
            "is_recent": recent,
        }

    async def _retrieve_node(self, state: AgentState) -> dict[str, Any]:
        tickers = await self._repository.list_followed_tickers(state["user_id"])
        requested = state.get("ticker")
        if requested:
            tickers = (requested,)
        if state["is_recommendation"]:
            persona = await self._repository.get_persona(state["user_id"])
            stocks = await self._repository.list_stocks_for_user(state["user_id"])
            ranked = self._ranker.rank(persona, stocks, limit=3)
            sources = await self._fundamentals_for(
                tuple(item.stock.ticker for item in ranked)
            )
            return {"recommendations": ranked, "sources": sources}
        if not tickers:
            return {"sources": ()}
        if state.get("is_recent"):
            recent_sources: list[SourceDocument] = []
            for followed_ticker in tickers:
                documents = await self._repository.list_documents(followed_ticker)
                news = sorted(
                    (item for item in documents if item.kind is DocumentKind.NEWS),
                    key=lambda item: item.published_at,
                    reverse=True,
                )
                fundamentals = next(
                    (
                        item
                        for item in documents
                        if item.kind is DocumentKind.FUNDAMENTALS
                    ),
                    None,
                )
                if fundamentals:
                    recent_sources.append(fundamentals)
                recent_sources.extend(news[:3])
            return {"sources": tuple(recent_sources[: self._retrieval_limit])}
        query_embedding = await self._embedder.embed(state["message"])
        sources = await self._repository.search_documents(
            query_embedding,
            tickers=tickers,
            limit=self._retrieval_limit,
        )
        return {"sources": self._fundamentals_first(sources)}

    async def _compose_node(self, state: AgentState) -> dict[str, Any]:
        sources = state.get("sources", ())
        if (
            state.get("persona_updated")
            and not state.get("is_recommendation")
            and not state.get("ticker")
        ):
            return {
                "draft": "I updated your investor persona and will use it for future research.",
                "citations": (),
            }
        if state.get("is_recommendation"):
            draft, citations = self._recommendation_draft(
                state.get("recommendations", ()), sources
            )
        else:
            draft, citations = await self._research_draft(state.get("ticker"), sources)
        generated = await self._generator.generate(draft, sources) if sources else draft
        return {"draft": generated, "citations": citations}

    async def _guard_node(self, state: AgentState) -> dict[str, Any]:
        grounded = self._guard.enforce(
            state.get("draft", GroundingGuard.FALLBACK),
            state.get("citations", ()),
            state.get("sources", ()),
        )
        return {
            "result": ChatResult(
                answer=grounded.answer,
                citations=grounded.citations,
                grounded=grounded.is_grounded,
                persona_updated=state.get("persona_updated", False),
                recommendations=state.get("recommendations", ()),
            )
        }

    async def _research_draft(
        self,
        ticker: str | None,
        sources: tuple[SourceDocument, ...],
    ) -> tuple[str, tuple[Citation, ...]]:
        if not sources:
            return GroundingGuard.FALLBACK, ()
        fundamentals = next(
            (source for source in sources if source.kind is DocumentKind.FUNDAMENTALS),
            None,
        )
        news = next(
            (source for source in sources if source.kind is DocumentKind.NEWS), None
        )
        selected = tuple(
            source for source in (fundamentals, news) if source is not None
        )
        citations = self._citations(selected)
        sentences: list[str] = []
        if fundamentals:
            stock = await self._repository.get_stock(ticker or fundamentals.ticker)
            if stock:
                sentences.append(f"{stock.name} trades at INR {stock.price_inr} [1].")
        if news:
            news_index = 2 if fundamentals else 1
            tone = (
                "positive"
                if news.sentiment > 0.15
                else "negative"
                if news.sentiment < -0.15
                else "neutral"
            )
            sentences.append(
                f"The latest retrieved reporting has a {tone} tone [{news_index}]."
            )
        elif fundamentals:
            sentences.append(
                "No matching recent news was retrieved for this ticker; the fundamentals source above is the latest indexed evidence [1]."
            )
        return " ".join(sentences) or GroundingGuard.FALLBACK, citations

    def _recommendation_draft(
        self,
        recommendations: tuple[RankedStock, ...],
        sources: tuple[SourceDocument, ...],
    ) -> tuple[str, tuple[Citation, ...]]:
        selected: list[SourceDocument] = []
        fundamentals_by_ticker: dict[str, SourceDocument] = {}
        news_by_ticker: dict[str, SourceDocument] = {}
        for item in recommendations:
            ticker_sources = [source for source in sources if source.ticker == item.stock.ticker]
            fundamentals = next(
                (source for source in ticker_sources if source.kind is DocumentKind.FUNDAMENTALS),
                None,
            )
            news = next(
                (source for source in ticker_sources if source.kind is DocumentKind.NEWS),
                None,
            )
            if fundamentals:
                fundamentals_by_ticker[item.stock.ticker] = fundamentals
                selected.append(fundamentals)
            if news:
                news_by_ticker[item.stock.ticker] = news
                selected.append(news)
        citations = self._citations(tuple(selected))
        index_by_source = {source.id: index for index, source in enumerate(selected, 1)}
        sentences: list[str] = []
        for item in recommendations:
            stock = item.stock
            fundamentals = fundamentals_by_ticker.get(stock.ticker)
            if fundamentals is None:
                continue
            fundamentals_index = index_by_source[fundamentals.id]
            metrics = [
                f"price is INR {stock.price_inr}",
                f"P/E ratio is {stock.pe_ratio}" if stock.pe_ratio is not None else "",
                f"debt-to-equity is {stock.debt_to_equity}" if stock.debt_to_equity is not None else "",
                f"return on equity is {stock.roe}%" if stock.roe is not None else "",
                f"revenue growth is {stock.revenue_growth}%" if stock.revenue_growth is not None else "",
            ]
            sentence = f"{stock.name}: {', '.join(metric for metric in metrics if metric)} [{fundamentals_index}]."
            news = news_by_ticker.get(stock.ticker)
            if news:
                news_index = index_by_source[news.id]
                tone = "positive" if news.sentiment > 0.15 else "negative" if news.sentiment < -0.15 else "neutral"
                sentence += f" Recent reporting on {stock.name} is {tone} [{news_index}]."
            sentences.append(sentence)
        return " ".join(sentences) or GroundingGuard.FALLBACK, citations

    async def _fundamentals_for(
        self, tickers: tuple[str, ...]
    ) -> tuple[SourceDocument, ...]:
        documents: list[SourceDocument] = []
        for ticker in tickers:
            ticker_documents = await self._repository.list_documents(ticker)
            fundamentals = next(
                (
                    item
                    for item in ticker_documents
                    if item.kind is DocumentKind.FUNDAMENTALS
                ),
                None,
            )
            news = next(
                (item for item in ticker_documents if item.kind is DocumentKind.NEWS),
                None,
            )
            if fundamentals:
                documents.append(fundamentals)
            if news:
                documents.append(news)
        return tuple(documents)

    @staticmethod
    def _fundamentals_first(
        sources: tuple[SourceDocument, ...],
    ) -> tuple[SourceDocument, ...]:
        return tuple(
            sorted(
                sources, key=lambda source: source.kind is not DocumentKind.FUNDAMENTALS
            )
        )

    @staticmethod
    def _citations(sources: tuple[SourceDocument, ...]) -> tuple[Citation, ...]:
        return tuple(
            Citation(
                index=index, document_id=source.id, title=source.title, url=source.url
            )
            for index, source in enumerate(sources, 1)
        )
