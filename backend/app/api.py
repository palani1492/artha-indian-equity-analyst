from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator

from app.auth import OAUTH_STATE_COOKIE
from app.container import Container, build_container
from app.domain.models import (
    ChatResult,
    IngestionResult,
    InvestorPersona,
    RiskTolerance,
    SourceDocument,
    Stock,
    normalize_ticker,
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    ticker: str | None = None

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("message cannot be blank")
        return cleaned

    @field_validator("ticker")
    @classmethod
    def clean_ticker(cls, value: str | None) -> str | None:
        return normalize_ticker(value)[0] if value else None


class TickerRequest(BaseModel):
    ticker: str

    @field_validator("ticker")
    @classmethod
    def clean_ticker(cls, value: str) -> str:
        normalize_ticker(value)
        return value.strip().upper()


class PersonaPatch(BaseModel):
    risk_tolerance: RiskTolerance | None = None
    style: str | None = Field(default=None, min_length=1, max_length=120)
    dividend_focused: bool | None = None
    avoid_high_debt: bool | None = None
    max_debt_to_equity: Decimal | None = Field(default=None, ge=0, le=20)
    preferred_sectors: tuple[str, ...] | None = None
    excluded_sectors: tuple[str, ...] | None = None
    priorities: tuple[str, ...] | None = None
    avoid: tuple[str, ...] | None = None
    horizon: str | None = Field(default=None, min_length=1, max_length=80)


class FollowResponse(BaseModel):
    ticker: str
    followed: bool
    ingestion: IngestionResult
    stock: Stock


class UnfollowResponse(BaseModel):
    ticker: str
    followed: bool = False


class OAuthConfigResponse(BaseModel):
    configured: bool
    client_id: str | None
    redirect_uri: str
    scopes: tuple[str, ...] = ("openid", "email", "profile")


def _container(request: Request) -> Container:
    return request.app.state.container


async def _user_id(
    request: Request, container: Annotated[Container, Depends(_container)]
) -> str:
    return await container.auth.current_user_id(request)


def create_app(container: Container | None = None) -> FastAPI:
    dependencies = container or build_container()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Keep process liveness independent of transient database availability.
        # `/health/ready` performs the schema-aware dependency check.
        yield

    app = FastAPI(
        title=dependencies.settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.container = dependencies
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(dependencies.settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-User-ID", "X-Request-ID"],
    )

    @app.get("/health")
    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok", "service": "sentellent-backend"}

    @app.get("/health/ready")
    @app.get("/api/health")
    async def readiness() -> dict[str, str]:
        healthy = await dependencies.repository.healthcheck()
        if not healthy:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="database unavailable",
            )
        return {"status": "ok", "service": "sentellent-backend"}

    @app.get("/api/v1/auth/google/config", response_model=OAuthConfigResponse)
    async def oauth_config() -> OAuthConfigResponse:
        settings = dependencies.settings
        return OAuthConfigResponse(
            configured=settings.google_oauth_configured,
            client_id=settings.google_client_id,
            redirect_uri=settings.google_redirect_uri,
        )

    @app.get("/api/v1/auth/google/login")
    async def oauth_login() -> RedirectResponse:
        response = RedirectResponse("/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
        response.headers["location"] = dependencies.auth.login_url(response)
        return response

    @app.get("/api/v1/auth/google/callback")
    async def oauth_callback(
        code: Annotated[str, Query(min_length=1, max_length=4096)],
        state_value: Annotated[
            str, Query(alias="state", min_length=1, max_length=4096)
        ],
        request: Request,
    ) -> RedirectResponse:
        state_cookie = request.cookies.get(OAUTH_STATE_COOKIE)
        limiter_key = dependencies.auth.callback_rate_limit_key(
            state_value, state_cookie
        )
        await dependencies.limiter.check(
            "oauth-callback",
            limiter_key,
            dependencies.settings.rate_limit_oauth_requests,
        )
        response = RedirectResponse(
            dependencies.settings.auth_success_url,
            status_code=status.HTTP_303_SEE_OTHER,
        )
        await dependencies.auth.callback(
            code=code,
            state=state_value,
            state_cookie=state_cookie,
            response=response,
        )
        return response

    @app.get("/api/v1/auth/me")
    async def me(user_id: Annotated[str, Depends(_user_id)]) -> dict[str, str | None]:
        user = await dependencies.repository.get_user(user_id)
        return user or {"id": user_id, "email": user_id, "name": None, "picture": None}

    @app.post("/api/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(request: Request, response: Response) -> Response:
        await dependencies.auth.logout(request, response)
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers=response.headers)

    @app.get("/api/v1/persona", response_model=InvestorPersona)
    @app.get("/api/persona", response_model=InvestorPersona)
    async def get_persona(
        user_id: Annotated[str, Depends(_user_id)],
    ) -> InvestorPersona:
        return await dependencies.repository.get_persona(user_id)

    async def update_persona(payload: PersonaPatch, user_id: str) -> InvestorPersona:
        current = await dependencies.repository.get_persona(user_id)
        updates = payload.model_dump(exclude_none=True)
        updated = current.model_copy(update={**updates, "version": current.version + 1})
        embedding = await dependencies.embedder.embed(
            str(updated.model_dump(mode="json"))
        )
        await dependencies.repository.save_persona(updated, embedding)
        return updated

    @app.patch("/api/v1/persona", response_model=InvestorPersona)
    async def patch_persona(
        payload: PersonaPatch, user_id: Annotated[str, Depends(_user_id)]
    ) -> InvestorPersona:
        return await update_persona(payload, user_id)

    @app.post("/api/persona", response_model=InvestorPersona)
    async def post_persona(
        payload: PersonaPatch, user_id: Annotated[str, Depends(_user_id)]
    ) -> InvestorPersona:
        return await update_persona(payload, user_id)

    @app.get("/api/v1/stocks", response_model=tuple[Stock, ...])
    @app.get("/api/stocks", response_model=tuple[Stock, ...])
    async def stocks(user_id: Annotated[str, Depends(_user_id)]) -> tuple[Stock, ...]:
        return await dependencies.repository.list_stocks_for_user(user_id)

    async def follow(ticker: str, user_id: str) -> FollowResponse:
        try:
            normalized, _ = normalize_ticker(ticker)
            ingestion = await dependencies.ingestion.ingest(ticker)
        except LookupError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
            ) from error
        followed = await dependencies.repository.follow_stock(user_id, normalized)
        stock = await dependencies.repository.get_stock(normalized)
        if stock is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="ingested stock was not persisted",
            )
        return FollowResponse(
            ticker=normalized,
            followed=followed,
            ingestion=ingestion,
            stock=stock,
        )

    @app.post(
        "/api/v1/stocks/{ticker}/follow",
        response_model=FollowResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def follow_stock(
        ticker: str, user_id: Annotated[str, Depends(_user_id)]
    ) -> FollowResponse:
        await dependencies.limiter.check(
            "follow", user_id, dependencies.settings.rate_limit_mutation_requests
        )
        try:
            return await follow(ticker, user_id)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error

    @app.delete(
        "/api/v1/stocks/{ticker}/follow",
        response_model=UnfollowResponse,
    )
    async def unfollow_stock(
        ticker: str, user_id: Annotated[str, Depends(_user_id)]
    ) -> UnfollowResponse:
        await dependencies.limiter.check(
            "unfollow", user_id, dependencies.settings.rate_limit_mutation_requests
        )
        try:
            normalized, _ = normalize_ticker(ticker)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error
        await dependencies.repository.unfollow_stock(user_id, normalized)
        return UnfollowResponse(ticker=normalized)

    @app.post(
        "/api/follow",
        response_model=FollowResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def follow_compat(
        payload: TickerRequest, user_id: Annotated[str, Depends(_user_id)]
    ) -> FollowResponse:
        await dependencies.limiter.check(
            "follow", user_id, dependencies.settings.rate_limit_mutation_requests
        )
        return await follow(payload.ticker, user_id)

    @app.post(
        "/api/v1/stocks/{ticker}/ingest",
        response_model=IngestionResult,
    )
    async def ingest_stock(
        ticker: str, user_id: Annotated[str, Depends(_user_id)]
    ) -> IngestionResult:
        await dependencies.limiter.check(
            "ingest", user_id, dependencies.settings.rate_limit_mutation_requests
        )
        try:
            return await dependencies.ingestion.ingest(ticker)
        except LookupError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
            ) from error

    @app.post("/api/ingest", response_model=IngestionResult)
    async def ingest_compat(
        payload: TickerRequest, user_id: Annotated[str, Depends(_user_id)]
    ) -> IngestionResult:
        await dependencies.limiter.check(
            "ingest", user_id, dependencies.settings.rate_limit_mutation_requests
        )
        try:
            return await dependencies.ingestion.ingest(payload.ticker)
        except LookupError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
            ) from error

    @app.get("/api/v1/sources", response_model=tuple[SourceDocument, ...])
    @app.get("/api/sources", response_model=tuple[SourceDocument, ...])
    async def sources(
        _: Annotated[str, Depends(_user_id)],
        ticker: str | None = Query(default=None, max_length=20),
    ) -> tuple[SourceDocument, ...]:
        normalized = normalize_ticker(ticker)[0] if ticker else None
        return await dependencies.repository.list_documents(normalized)

    async def chat(payload: ChatRequest, user_id: str) -> ChatResult:
        return await dependencies.agent.chat(user_id, payload.message, payload.ticker)

    @app.post("/api/v1/chat", response_model=ChatResult)
    async def chat_v1(
        payload: ChatRequest, user_id: Annotated[str, Depends(_user_id)]
    ) -> ChatResult:
        await dependencies.limiter.check(
            "chat", user_id, dependencies.settings.rate_limit_chat_requests
        )
        return await chat(payload, user_id)

    @app.post("/api/chat", response_model=ChatResult)
    async def chat_compat(
        payload: ChatRequest, user_id: Annotated[str, Depends(_user_id)]
    ) -> ChatResult:
        await dependencies.limiter.check(
            "chat", user_id, dependencies.settings.rate_limit_chat_requests
        )
        return await chat(payload, user_id)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if dependencies.settings.app_env == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        return response

    return app


app = create_app()
