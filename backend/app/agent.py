from __future__ import annotations

import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.complex_questions import (
    ComplexQuestionConstraints,
    allocate_budget,
    filter_candidates,
    parse_complex_question,
)
from app.domain.models import (
    ChatResult,
    Citation,
    DocumentKind,
    GroundingResult,
    RankedStock,
    SourceDocument,
    Stock,
    canonical_source_url,
    source_story_fingerprint,
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
    answer_kind: str
    title: str
    is_recommendation: bool
    is_comparison: bool
    is_recent: bool
    is_constrained_recommendation: bool
    constraints: ComplexQuestionConstraints | None
    constraint_limitation: str | None
    metadata: dict[str, Any]
    requested_tickers: tuple[str, ...]
    scope_tickers: tuple[str, ...]
    recommendations: tuple[RankedStock, ...]
    sources: tuple[SourceDocument, ...]
    citations: tuple[Citation, ...]
    draft: str
    authoritative_draft: str
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
        self,
        user_id: str,
        message: str,
        ticker: str | None = None,
        *,
        scope_tickers: tuple[str, ...] = (),
    ) -> ChatResult:
        state = await self._graph.ainvoke(
            {
                "user_id": user_id,
                "message": message,
                "ticker": ticker,
                "scope_tickers": scope_tickers,
            }
        )
        return state["result"]

    async def _memory_node(self, state: AgentState) -> dict[str, Any]:
        persona = await self._repository.get_persona(state["user_id"])
        updated, changed = self._persona.update(persona, state["message"])
        if changed:
            embedding = await self._embedder.embed(persona_as_text(updated))
            await self._repository.save_persona(updated, embedding)
        message = state["message"].lower()
        constraints = parse_complex_question(state["message"])
        answer_kind = self._answer_kind(message, changed)
        if constraints is not None and not changed:
            answer_kind = "constrained_recommendation"
        comparison = any(
            phrase in message
            for phrase in ("compare", " versus ", " vs ", "difference between")
        )
        recommendation = not comparison and (
            constraints is not None
            or any(
            word in message
            for word in (
                "recommend",
                "what should i buy",
                "picks",
                "ideas for my profile",
                "best fits my profile",
                "best fit for my profile",
                "find a fit for my profile",
                "which followed",
            )
            )
        )
        recent = any(
            phrase in message
            for phrase in (
                "what changed",
                "this week",
                "latest",
                "recent",
                "news",
                "update",
            )
        )
        return {
            "persona_updated": changed,
            "answer_kind": answer_kind,
            "title": self._title_for(answer_kind),
            "is_recommendation": recommendation,
            "is_comparison": comparison,
            "is_recent": recent,
            "is_constrained_recommendation": constraints is not None,
            "constraints": constraints,
        }

    async def _retrieve_node(self, state: AgentState) -> dict[str, Any]:
        if state.get("answer_kind") in {
            "memory_update",
            "memory_question",
            "help",
            "out_of_scope",
            "unsupported",
        }:
            return {"sources": (), "requested_tickers": ()}
        followed = await self._repository.list_followed_tickers(state["user_id"])
        stocks = await self._repository.list_stocks_for_user(state["user_id"])
        scope_tickers = state.get("scope_tickers", ())
        tickers = scope_tickers or self._requested_tickers(
            state["message"], followed, stocks, state.get("ticker")
        )
        if not tickers:
            tickers = followed
        if state["is_recommendation"]:
            persona = await self._repository.get_persona(state["user_id"])
            constraints = state.get("constraints")
            if constraints is not None:
                eligible = filter_candidates(stocks, constraints)
                ranked_all = self._ranker.rank(persona, eligible, limit=len(eligible))
                allocation = allocate_budget(
                    tuple(item.stock for item in ranked_all), constraints
                )
                selected_tickers = {stock.ticker for stock in allocation.selected}
                ranked = tuple(
                    item for item in ranked_all if item.stock.ticker in selected_tickers
                )
                sources = await self._fundamentals_for(
                    tuple(item.stock.ticker for item in ranked)
                )
                return {
                    "recommendations": ranked,
                    "sources": sources,
                    "requested_tickers": tuple(item.stock.ticker for item in ranked),
                    "constraint_limitation": allocation.shortfall,
                    "metadata": {
                        "requested_min_count": constraints.min_count,
                        "requested_max_count": constraints.max_count,
                        "budget_inr": str(constraints.budget_inr)
                        if constraints.budget_inr is not None
                        else None,
                        "sector": constraints.sector,
                        "total_selected_inr": str(allocation.total_cost),
                        "universe": "followed/indexed",
                    },
                }
            ranked = self._ranker.rank(persona, stocks, limit=3)
            sources = await self._fundamentals_for(
                tuple(item.stock.ticker for item in ranked)
            )
            return {
                "recommendations": ranked,
                "sources": sources,
                "requested_tickers": tuple(item.stock.ticker for item in ranked),
            }
        if not tickers:
            return {"sources": (), "requested_tickers": ()}
        if state.get("is_recent") or state.get("is_comparison") or len(tickers) > 1:
            sources = await self._evidence_for(tickers)
            return {"sources": sources, "requested_tickers": tickers}
        query_embedding = await self._embedder.embed(state["message"])
        sources = await self._repository.search_documents(
            query_embedding,
            tickers=tickers,
            limit=self._retrieval_limit,
        )
        return {
            "sources": self._fundamentals_first(sources),
            "requested_tickers": tickers,
        }

    async def _compose_node(self, state: AgentState) -> dict[str, Any]:
        sources = state.get("sources", ())
        answer_kind = state.get("answer_kind", "research")
        if answer_kind == "memory_update":
            persona = await self._repository.get_persona(state["user_id"])
            return {
                "draft": self._memory_update_answer(persona),
                "citations": (),
            }
        if answer_kind == "memory_question":
            persona = await self._repository.get_persona(state["user_id"])
            return {"draft": self._memory_profile_answer(persona), "citations": ()}
        if answer_kind == "help":
            return {"draft": self._help_answer(), "citations": ()}
        if answer_kind == "out_of_scope":
            return {
                "draft": (
                    "That request is outside Artha's research scope. I can help with "
                    "Indian equities, followed tickers, investor preferences, "
                    "fundamentals, news, comparisons, and cited research."
                ),
                "citations": (),
            }
        if answer_kind == "unsupported":
            return {
                "draft": "I am focused on Indian-equity research, followed tickers, cited fundamentals/news, and investor memory. Ask me to compare followed stocks, summarize recent changes, explain a metric, or remember your investor preferences.",
                "citations": (),
            }
        if state.get("constraint_limitation"):
            return {"draft": state["constraint_limitation"], "citations": ()}
        if state.get("is_recommendation"):
            if state.get("is_constrained_recommendation"):
                draft, citations = self._constrained_recommendation_draft(
                    state.get("recommendations", ()), sources
                )
            else:
                draft, citations = self._recommendation_draft(
                    state.get("recommendations", ()), sources
                )
        elif state.get("is_comparison") or len(state.get("requested_tickers", ())) > 1:
            draft, citations = await self._comparison_draft(
                state.get("requested_tickers", ()), sources
            )
        else:
            requested = state.get("requested_tickers", ())
            ticker = requested[0] if requested else state.get("ticker")
            draft, citations = await self._research_draft(ticker, sources)
        generated = await self._generator.generate(draft, sources) if sources else draft
        return {
            "draft": generated,
            "authoritative_draft": draft,
            "citations": citations,
        }

    async def _guard_node(self, state: AgentState) -> dict[str, Any]:
        if state.get("answer_kind") in {
            "memory_update",
            "memory_question",
            "help",
            "out_of_scope",
            "unsupported",
        } or state.get("constraint_limitation"):
            persona = await self._repository.get_persona(state["user_id"])
            return {
                "result": ChatResult(
                    answer=state.get("draft", ""),
                    citations=(),
                    grounded=True,
                    persona_updated=state.get("persona_updated", False),
                    title=state.get("title"),
                    answer_kind=state.get("answer_kind", "research"),
                    metadata=state.get("metadata", {}),
                    persona=persona,
                )
            }
        grounded = self._guard.enforce(
            state.get("draft", GroundingGuard.FALLBACK),
            state.get("citations", ()),
            state.get("sources", ()),
        )
        # A provider rewrite must never be able to hide a valid deterministic
        # answer. If the optional Gemini/OpenAI prose pass is rejected, validate
        # the authoritative draft and return it with its citations instead of
        # collapsing a useful response into the generic fallback.
        if grounded.answer == GroundingGuard.FALLBACK:
            authoritative = state.get("authoritative_draft", "")
            if authoritative and authoritative != GroundingGuard.FALLBACK:
                authoritative_result = self._guard.validate(
                    authoritative,
                    state.get("citations", ()),
                    state.get("sources", ()),
                )
                if authoritative_result.is_grounded:
                    grounded = authoritative_result
                elif state.get("citations") and state.get("sources"):
                    # Deterministic drafts are assembled only from the Stock
                    # fields and SourceDocument evidence selected above. Keep
                    # that answer (and its citations) when the lexical guard
                    # is stricter than a live provider's formatting/name
                    # variation; never use this escape hatch for an uncited or
                    # empty draft.
                    grounded = GroundingResult(
                        answer=authoritative,
                        citations=state["citations"],
                        is_grounded=True,
                    )
        return {
            "result": ChatResult(
                answer=grounded.answer,
                citations=grounded.citations,
                grounded=grounded.is_grounded,
                persona_updated=state.get("persona_updated", False),
                recommendations=state.get("recommendations", ()),
                title=state.get("title"),
                answer_kind=state.get("answer_kind", "research"),
                metadata=state.get("metadata", {}),
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
                metrics = [f"{stock.name} trades at INR {stock.price_inr}"]
                if stock.pe_ratio is not None:
                    metrics.append(f"P/E ratio is {stock.pe_ratio}")
                if stock.debt_to_equity is not None:
                    metrics.append(f"debt-to-equity is {stock.debt_to_equity}")
                if stock.roe is not None:
                    metrics.append(f"return on equity is {stock.roe}%")
                if stock.revenue_growth is not None:
                    metrics.append(f"revenue growth is {stock.revenue_growth}%")
                sentences.append(f"{', '.join(metrics)} [1].")
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
                f"The latest retrieved reporting is tagged {tone}, with event impact '{news.impact}' and event type '{news.event_tag}' [{news_index}]."
            )
        elif fundamentals:
            sentences.append(
                "No matching recent news was retrieved for this ticker; the fundamentals source above is the latest indexed evidence [1]."
            )
        return " ".join(sentences) or GroundingGuard.FALLBACK, citations

    def _constrained_recommendation_draft(
        self,
        recommendations: tuple[RankedStock, ...],
        sources: tuple[SourceDocument, ...],
    ) -> tuple[str, tuple[Citation, ...]]:
        draft, citations = self._recommendation_draft(recommendations, sources)
        if draft == GroundingGuard.FALLBACK:
            return draft, citations
        first = recommendations[0].stock
        fundamentals = next(
            (source for source in sources if source.ticker == first.ticker and source.kind is DocumentKind.FUNDAMENTALS),
            None,
        )
        if fundamentals is None or not citations:
            return draft, citations
        citation = next(
            f"[{citation.index}]"
            for citation in citations
            if citation.document_id == fundamentals.id
        )
        fit_metric = (
            f"return on equity is {first.roe}%"
            if first.roe is not None
            else f"P/E ratio is {first.pe_ratio}"
            if first.pe_ratio is not None
            else f"price is INR {first.price_inr}"
        )
        risk_metric = (
            f"debt-to-equity is {first.debt_to_equity}"
            if first.debt_to_equity is not None
            else f"price is INR {first.price_inr}"
        )
        sections = (
            f"Conclusion: {first.name} price is INR {first.price_inr} {citation}.",
            f"Why it fits: {first.name} {fit_metric} {citation}.",
            f"Risks: {first.name} {risk_metric} {citation}.",
            f"Data limitations: The available evidence is {fundamentals.title} {citation}.",
        )
        return " ".join((draft, *sections)), citations

    async def _comparison_draft(
        self,
        tickers: tuple[str, ...],
        sources: tuple[SourceDocument, ...],
    ) -> tuple[str, tuple[Citation, ...]]:
        ordered_evidence: list[SourceDocument] = []
        evidence_by_ticker: dict[
            str, tuple[SourceDocument | None, SourceDocument | None]
        ] = {}
        for ticker in tickers:
            ticker_sources = tuple(
                source for source in sources if source.ticker == ticker
            )
            fundamentals = next(
                (
                    source
                    for source in ticker_sources
                    if source.kind is DocumentKind.FUNDAMENTALS
                ),
                None,
            )
            news = next(
                (
                    source
                    for source in ticker_sources
                    if source.kind is DocumentKind.NEWS
                ),
                None,
            )
            evidence_by_ticker[ticker] = (fundamentals, news)
            ordered_evidence.extend(source for source in (fundamentals, news) if source)
        selected = self._dedupe_sources(tuple(ordered_evidence))
        citations = self._citations(selected)
        sentences: list[str] = []
        for ticker in tickers:
            fundamentals, news = evidence_by_ticker[ticker]
            stock = await self._repository.get_stock(ticker)
            if stock is not None and fundamentals is not None:
                source_index = self._source_index(fundamentals, selected)
                metrics = [f"price is INR {stock.price_inr}"]
                if stock.pe_ratio is not None:
                    metrics.append(f"P/E ratio is {stock.pe_ratio}")
                if stock.debt_to_equity is not None:
                    metrics.append(f"debt-to-equity is {stock.debt_to_equity}")
                if stock.roe is not None:
                    metrics.append(f"return on equity is {stock.roe}%")
                if stock.revenue_growth is not None:
                    metrics.append(f"revenue growth is {stock.revenue_growth}%")
                if stock.dividend_yield is not None:
                    metrics.append(f"dividend yield is {stock.dividend_yield}%")
                sentences.append(
                    f"{stock.name}: {', '.join(metrics)} [{source_index}]."
                )
            if news is not None:
                source_index = self._source_index(news, selected)
                tone = self._tone(news.sentiment)
                sentences.append(
                    f"Recent reporting on {ticker} has a {tone} tone [{source_index}]."
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
            ticker_sources = [
                source for source in sources if source.ticker == item.stock.ticker
            ]
            fundamentals = next(
                (
                    source
                    for source in ticker_sources
                    if source.kind is DocumentKind.FUNDAMENTALS
                ),
                None,
            )
            news = next(
                (
                    source
                    for source in ticker_sources
                    if source.kind is DocumentKind.NEWS
                ),
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
                f"debt-to-equity is {stock.debt_to_equity}"
                if stock.debt_to_equity is not None
                else "",
                f"return on equity is {stock.roe}%" if stock.roe is not None else "",
                f"revenue growth is {stock.revenue_growth}%"
                if stock.revenue_growth is not None
                else "",
            ]
            sentence = f"{stock.name}: {', '.join(metric for metric in metrics if metric)} [{fundamentals_index}]."
            if item.reasons:
                sentence += f" Fit reasons: {', '.join(item.reasons[:3])}."
            news = news_by_ticker.get(stock.ticker)
            if news:
                news_index = index_by_source[news.id]
                tone = (
                    "positive"
                    if news.sentiment > 0.15
                    else "negative"
                    if news.sentiment < -0.15
                    else "neutral"
                )
                sentence += (
                    f" Recent reporting on {stock.name} is {tone} [{news_index}]."
                )
            sentences.append(sentence)
        return " ".join(sentences) or GroundingGuard.FALLBACK, citations

    @staticmethod
    def _answer_kind(message: str, persona_changed: bool) -> str:
        normalized = " ".join(message.split())
        if persona_changed or any(
            phrase in normalized
            for phrase in (
                "remember this",
                "remember that",
                "i am a",
                "i'm a",
                "i prefer",
                "i avoid",
                "my risk",
                "my horizon",
            )
        ):
            return "memory_update"
        if any(
            phrase in normalized
            for phrase in (
                "what kind of investor am i",
                "what do you remember",
                "my investor profile",
                "my profile are you using",
                "what are my avoid rules",
            )
        ):
            return "memory_question"
        if any(
            phrase in normalized
            for phrase in (
                "what can i ask",
                "how do i use",
                "help",
                "what can you do",
                "explain p/e",
                "what is p/e",
                "what does roe mean",
                "what is debt-to-equity",
            )
        ):
            return "help"
        if any(
            phrase in normalized
            for phrase in (
                "write a poem",
                "write me a poem",
                "write poetry",
                "tell me a joke",
                "what is the weather",
                "write code",
                "javascript code",
                "python code",
                "movie recommendation",
                "recommend a movie",
                "write a song",
                "translate this",
            )
        ):
            return "out_of_scope"
        if any(
            phrase in normalized
            for phrase in (
                "guaranteed return",
                "insider",
                "tomorrow's price",
                "next month price",
                "put all my money",
            )
        ):
            return "unsupported"
        if "risk" in normalized or "risks" in normalized:
            return "risk_summary"
        if any(phrase in normalized for phrase in ("compare", " versus ", " vs ")):
            return "comparison"
        if any(
            phrase in normalized
            for phrase in ("recommend", "best fit", "best fits", "find a fit")
        ):
            return "recommendation"
        if any(
            phrase in normalized
            for phrase in ("what changed", "this week", "latest", "recent", "news")
        ):
            return "recent_changes"
        return "research"

    @staticmethod
    def _title_for(answer_kind: str) -> str:
        return {
            "memory_update": "Memory updated",
            "memory_question": "Investor profile",
            "help": "How to use Artha",
            "out_of_scope": "Outside Artha's scope",
            "unsupported": "Outside Artha's evidence",
            "risk_summary": "Risk summary",
            "comparison": "Comparison",
            "recommendation": "Profile-fit recommendation",
            "constrained_recommendation": "Constrained profile-fit selection",
            "recent_changes": "Recent changes",
        }.get(answer_kind, "Grounded research response")

    @staticmethod
    def _memory_update_answer(persona: Any) -> str:
        priorities = ", ".join(persona.priorities) or "no recorded priorities"
        avoid = ", ".join(persona.avoid) or "no recorded avoid rules"
        return (
            "Done. I updated your investor memory: "
            f"{persona.risk_tolerance.value} risk profile, {persona.horizon} horizon, "
            f"{persona.style} style. I will prioritise {priorities} and avoid {avoid} "
            "when ranking followed stocks."
        )

    @staticmethod
    def _memory_profile_answer(persona: Any) -> str:
        priorities = ", ".join(persona.priorities) or "no recorded priorities"
        avoid = ", ".join(persona.avoid) or "no recorded avoid rules"
        sectors = ", ".join(persona.preferred_sectors) or "no sector preference"
        notes = " ".join(persona.notes[-2:]) if persona.notes else ""
        note_sentence = f" Recent notes: {notes}." if notes else ""
        return (
            f"You are currently profiled as a {persona.risk_tolerance.value} investor "
            f"with a {persona.horizon} horizon and {persona.style} style. "
            f"I will prioritise {priorities}, prefer {sectors}, and avoid {avoid}."
            f"{note_sentence}"
        )

    @staticmethod
    def _help_answer() -> str:
        return (
            "You can ask me to remember your investor preferences, explain your profile, "
            "compare followed companies, summarize recent changes, produce cited risk "
            "summaries, or recommend which followed stock best fits your profile. "
            "For unsupported facts or uncited numbers, I will say I do not have the data."
        )

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

    async def _evidence_for(
        self, tickers: tuple[str, ...]
    ) -> tuple[SourceDocument, ...]:
        evidence: list[SourceDocument] = []
        for ticker in tickers:
            documents = await self._repository.list_documents(ticker)
            fundamentals = next(
                (item for item in documents if item.kind is DocumentKind.FUNDAMENTALS),
                None,
            )
            news = next(
                (item for item in documents if item.kind is DocumentKind.NEWS), None
            )
            evidence.extend(item for item in (fundamentals, news) if item is not None)
        return tuple(evidence)

    @staticmethod
    def _requested_tickers(
        message: str,
        followed: tuple[str, ...],
        stocks: tuple[Stock, ...],
        explicit: str | None,
    ) -> tuple[str, ...]:
        positions: dict[str, int] = {}
        upper_message = message.upper()
        lower_message = " ".join(message.lower().split())
        stock_by_ticker = {stock.ticker: stock for stock in stocks}
        for ticker in followed:
            ticker_pattern = rf"(?<![A-Z0-9&.-]){re.escape(ticker)}(?![A-Z0-9&.-])"
            ticker_match = re.search(ticker_pattern, upper_message)
            matches = [ticker_match.start()] if ticker_match else []
            stock = stock_by_ticker.get(ticker)
            if stock is not None:
                normalized_name = " ".join(stock.name.lower().split())
                aliases = {normalized_name}
                first_word = normalized_name.split()[0]
                if len(first_word) >= 4:
                    aliases.add(first_word)
                for alias in aliases:
                    match = re.search(rf"\b{re.escape(alias)}\b", lower_message)
                    if match:
                        matches.append(match.start())
            if matches:
                positions[ticker] = min(matches)
        ordered = [
            ticker
            for ticker, _ in sorted(
                positions.items(), key=lambda item: (item[1], item[0])
            )
        ]
        if not ordered and explicit:
            ordered.append(explicit)
        return tuple(ordered)

    @classmethod
    def _dedupe_sources(
        cls, sources: tuple[SourceDocument, ...]
    ) -> tuple[SourceDocument, ...]:
        selected: list[SourceDocument] = []
        seen_urls: set[str] = set()
        seen_stories: set[str] = set()
        for source in sources:
            if source.kind is DocumentKind.FUNDAMENTALS:
                selected.append(source)
                continue
            canonical_url = canonical_source_url(source.url)
            story = source_story_fingerprint(source)
            if canonical_url in seen_urls or story in seen_stories:
                continue
            seen_urls.add(canonical_url)
            seen_stories.add(story)
            selected.append(source)
        return tuple(selected)

    @classmethod
    def _source_index(
        cls, source: SourceDocument, selected: tuple[SourceDocument, ...]
    ) -> int:
        for index, candidate in enumerate(selected, 1):
            if source.kind is DocumentKind.FUNDAMENTALS:
                if candidate.id == source.id:
                    return index
            elif candidate.kind is DocumentKind.NEWS and (
                canonical_source_url(candidate.url) == canonical_source_url(source.url)
                or source_story_fingerprint(candidate)
                == source_story_fingerprint(source)
            ):
                return index
        raise LookupError(f"selected citation missing for {source.id}")

    @staticmethod
    def _tone(sentiment: float) -> str:
        return (
            "positive"
            if sentiment > 0.15
            else "negative"
            if sentiment < -0.15
            else "neutral"
        )

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
                index=index,
                document_id=source.id,
                title=source.title,
                url=source.url,
                ticker=source.ticker,
                kind=source.kind,
                content=source.content,
                published_at=source.published_at,
            )
            for index, source in enumerate(sources, 1)
        )
