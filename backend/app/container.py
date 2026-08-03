from __future__ import annotations

from dataclasses import dataclass

from app.agent import EquityResearchAgent
from app.auth import GoogleOidcService
from app.embeddings import (
    DeterministicEmbedder,
    OpenAIEmbedder,
    ResilientCachedEmbedder,
)
from app.gemini import GeminiTextClient
from app.generation import (
    ClaimPreservingAnswerGenerator,
    GeminiAnswerGenerator,
    OpenAIAnswerGenerator,
    ResilientAnswerGenerator,
)
from app.ingestion import IngestionService
from app.providers import (
    DemoMarketDataProvider,
    LiveIndianMarketDataProvider,
    MarketDataProvider,
)
from app.rate_limit import FixedWindowRateLimiter
from app.repositories.base import ResearchRepository
from app.repositories.memory import InMemoryResearchRepository
from app.repositories.sql import SqlAlchemyResearchRepository
from app.settings import Settings
from app.tagging import GeminiArticleTagger, OpenAIArticleTagger, ResilientArticleTagger


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    repository: ResearchRepository
    embedder: ResilientCachedEmbedder
    ingestion: IngestionService
    agent: EquityResearchAgent
    auth: GoogleOidcService
    limiter: FixedWindowRateLimiter


def build_container(settings: Settings | None = None) -> Container:
    runtime = settings or Settings()
    repository: ResearchRepository
    database_url = runtime.resolved_database_url
    if database_url:
        repository = SqlAlchemyResearchRepository(database_url)
    elif runtime.app_env == "production":
        raise ValueError(
            "Persistent DATABASE_URL or DB_* configuration is required in production"
        )
    else:
        repository = InMemoryResearchRepository()
    provider: MarketDataProvider
    if runtime.market_data_provider.lower() == "live":
        provider = LiveIndianMarketDataProvider(
            rss_feeds=runtime.rss_feeds,
            request_timeout_seconds=runtime.rss_request_timeout_seconds,
            min_request_interval_seconds=runtime.rss_min_request_interval_seconds,
        )
    else:
        provider = DemoMarketDataProvider()
    local_embedder = DeterministicEmbedder()
    openai_embedder = None
    openai_generator = None
    openai_tagger = None
    gemini_client = None
    if runtime.ai_provider.lower() == "openai" and runtime.openai_api_key:
        openai_embedder = OpenAIEmbedder(
            runtime.openai_api_key, runtime.openai_embedding_model
        )
        openai_generator = OpenAIAnswerGenerator(
            runtime.openai_api_key, runtime.openai_chat_model
        )
        openai_tagger = OpenAIArticleTagger(
            runtime.openai_api_key, runtime.openai_chat_model
        )
    if runtime.ai_provider.lower() == "gemini" and runtime.gemini_api_key:
        gemini_client = GeminiTextClient(
            runtime.gemini_api_key, runtime.gemini_model
        )
    embedder = ResilientCachedEmbedder(openai_embedder, local_embedder)
    primary_generator = (
        GeminiAnswerGenerator(gemini_client)
        if gemini_client is not None
        else openai_generator
    )
    generator = ClaimPreservingAnswerGenerator(
        ResilientAnswerGenerator(primary_generator)
    )
    primary_tagger = (
        GeminiArticleTagger(gemini_client)
        if gemini_client is not None
        else openai_tagger
    )
    tagger = ResilientArticleTagger(primary_tagger)
    ingestion = IngestionService(repository, provider, embedder, tagger)
    agent = EquityResearchAgent(
        repository, embedder, generator, runtime.retrieval_limit
    )
    auth = GoogleOidcService(runtime, repository)
    limiter = FixedWindowRateLimiter(runtime.rate_limit_window_seconds)
    return Container(
        settings=runtime,
        repository=repository,
        embedder=embedder,
        ingestion=ingestion,
        agent=agent,
        auth=auth,
        limiter=limiter,
    )
