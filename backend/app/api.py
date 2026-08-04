from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator

from app.auth import OAUTH_STATE_COOKIE
from app.container import Container, build_container
from app.domain.models import (
    ChatResult,
    Citation,
    ConversationMessage,
    IngestionResult,
    InvestorPersona,
    ResearchConversation,
    ResearchNote,
    RiskTolerance,
    SourceDocument,
    Stock,
    normalize_ticker,
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    ticker: str | None = None
    tickers: tuple[str, ...] = Field(default=(), max_length=10)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)

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

    @field_validator("tickers")
    @classmethod
    def clean_tickers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(normalize_ticker(value)[0] for value in values))
        return normalized


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


class RefreshResponse(BaseModel):
    results: tuple[IngestionResult, ...]
    stocks: tuple[Stock, ...]
    failed: tuple[str, ...] = ()


class UnfollowResponse(BaseModel):
    ticker: str
    followed: bool = False


class OAuthConfigResponse(BaseModel):
    configured: bool
    client_id: str | None
    redirect_uri: str
    scopes: tuple[str, ...] = ("openid", "email", "profile")


class ConversationCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return value.strip()


class NoteRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=4000)
    scope_tickers: tuple[str, ...] = Field(default=(), max_length=10)
    citations: tuple[Citation, ...] = Field(default=(), max_length=20)

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


def _container(request: Request) -> Container:
    return request.app.state.container


async def _user_id(
    request: Request, container: Annotated[Container, Depends(_container)]
) -> str:
    return await container.auth.current_user_id(request)


async def _admin_user(
    request: Request, container: Annotated[Container, Depends(_container)]
) -> dict[str, str | None]:
    user_id = await container.auth.current_user_id(request)
    user = await container.repository.get_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user record required",
        )
    email = user.get("email")
    if not email or email.casefold() not in container.settings.admin_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return user


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

    @app.get("/api/v1/conversations", response_model=tuple[ResearchConversation, ...])
    async def conversations(
        user_id: Annotated[str, Depends(_user_id)],
    ) -> tuple[ResearchConversation, ...]:
        return await dependencies.repository.list_conversations(user_id)

    @app.post(
        "/api/v1/conversations",
        response_model=ResearchConversation,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_conversation(
        payload: ConversationCreateRequest,
        user_id: Annotated[str, Depends(_user_id)],
    ) -> ResearchConversation:
        now = datetime.now(UTC)
        conversation = ResearchConversation(
            id=uuid4().hex,
            user_id=user_id,
            title=payload.title,
            created_at=now,
            updated_at=now,
        )
        await dependencies.repository.create_conversation(conversation)
        return conversation

    @app.get(
        "/api/v1/conversations/{conversation_id}/messages",
        response_model=tuple[ConversationMessage, ...],
    )
    async def conversation_messages(
        conversation_id: Annotated[str, Path(min_length=1, max_length=64)],
        user_id: Annotated[str, Depends(_user_id)],
    ) -> tuple[ConversationMessage, ...]:
        if (
            await dependencies.repository.get_conversation(user_id, conversation_id)
            is None
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
            )
        return await dependencies.repository.list_conversation_messages(user_id, conversation_id)

    @app.get("/api/v1/notes", response_model=tuple[ResearchNote, ...])
    async def notes(user_id: Annotated[str, Depends(_user_id)]) -> tuple[ResearchNote, ...]:
        return await dependencies.repository.list_notes(user_id)

    @app.post(
        "/api/v1/notes", response_model=ResearchNote, status_code=status.HTTP_201_CREATED
    )
    async def create_note(
        payload: NoteRequest, user_id: Annotated[str, Depends(_user_id)]
    ) -> ResearchNote:
        now = datetime.now(UTC)
        note = ResearchNote(
            id=uuid4().hex,
            user_id=user_id,
            created_at=now,
            updated_at=now,
            **payload.model_dump(),
        )
        await dependencies.repository.create_note(note)
        return note

    @app.patch("/api/v1/notes/{note_id}", response_model=ResearchNote)
    async def update_note(
        note_id: Annotated[str, Path(min_length=1, max_length=64)],
        payload: NoteRequest,
        user_id: Annotated[str, Depends(_user_id)],
    ) -> ResearchNote:
        current = await dependencies.repository.get_note(user_id, note_id)
        if current is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Note not found"
            )
        note = ResearchNote(
            id=current.id,
            user_id=user_id,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
            **payload.model_dump(),
        )
        await dependencies.repository.update_note(note)
        return note

    @app.delete("/api/v1/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_note(
        note_id: Annotated[str, Path(min_length=1, max_length=64)],
        user_id: Annotated[str, Depends(_user_id)],
    ) -> Response:
        if not await dependencies.repository.delete_note(user_id, note_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Note not found"
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/v1/admin/users", response_model=tuple[dict[str, str | None], ...])
    async def admin_users(
        _: Annotated[dict[str, str | None], Depends(_admin_user)],
    ) -> tuple[dict[str, str | None], ...]:
        return await dependencies.repository.list_users()

    @app.post("/api/v1/admin/users/{user_id}/reset-profile")
    async def admin_reset_profile(
        user_id: Annotated[str, Path(min_length=1, max_length=320, pattern=r"^\S+$")],
        _: Annotated[dict[str, str | None], Depends(_admin_user)],
    ) -> dict[str, str | bool]:
        if not await dependencies.repository.reset_user_profile(user_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        return {"id": user_id, "reset": True}

    @app.post("/api/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(request: Request, response: Response) -> Response:
        await dependencies.auth.logout(request, response)
        return Response(
            status_code=status.HTTP_204_NO_CONTENT, headers=response.headers
        )

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

    @app.post("/api/v1/refresh", response_model=RefreshResponse)
    @app.post("/api/refresh", response_model=RefreshResponse)
    async def refresh_followed(
        user_id: Annotated[str, Depends(_user_id)],
    ) -> RefreshResponse:
        await dependencies.limiter.check(
            "refresh", user_id, dependencies.settings.rate_limit_mutation_requests
        )
        results: list[IngestionResult] = []
        failed: list[str] = []
        for followed_ticker in await dependencies.repository.list_followed_tickers(
            user_id
        ):
            try:
                results.append(await dependencies.ingestion.ingest(followed_ticker))
            except (
                KeyError,
                LookupError,
                OSError,
                RuntimeError,
                TimeoutError,
                TypeError,
                ValueError,
            ):
                # A single upstream ticker must not prevent other followed
                # equities from refreshing in the same automatic pass.
                failed.append(followed_ticker)
        return RefreshResponse(
            results=tuple(results),
            stocks=await dependencies.repository.list_stocks_for_user(user_id),
            failed=tuple(failed),
        )

    @app.get("/api/v1/sources", response_model=tuple[SourceDocument, ...])
    @app.get("/api/sources", response_model=tuple[SourceDocument, ...])
    async def sources(
        _: Annotated[str, Depends(_user_id)],
        ticker: str | None = Query(default=None, max_length=20),
    ) -> tuple[SourceDocument, ...]:
        normalized = normalize_ticker(ticker)[0] if ticker else None
        await dependencies.repository.deduplicate_documents(normalized)
        return await dependencies.repository.list_documents(normalized)

    async def chat(payload: ChatRequest, user_id: str) -> ChatResult:
        conversation_id = payload.conversation_id
        if conversation_id is None:
            now = datetime.now(UTC)
            conversation = ResearchConversation(
                id=uuid4().hex,
                user_id=user_id,
                title=payload.message[:200],
                created_at=now,
                updated_at=now,
            )
            await dependencies.repository.create_conversation(conversation)
            conversation_id = conversation.id
        elif (
            await dependencies.repository.get_conversation(user_id, conversation_id)
            is None
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
            )
        await dependencies.repository.add_conversation_message(
            ConversationMessage(
                id=uuid4().hex,
                conversation_id=conversation_id,
                role="user",
                text=payload.message,
                scope_tickers=payload.tickers or ((payload.ticker,) if payload.ticker else ()),
                created_at=datetime.now(UTC),
            )
        )
        # A user can arrive with an existing follow after a deploy or a failed
        # background refresh. Ensure every requested/followed ticker has at
        # least one indexed snapshot before retrieval, while keeping upstream
        # failures isolated to that ticker.
        followed_tickers = await dependencies.repository.list_followed_tickers(user_id)
        requested_scope = payload.tickers or ((payload.ticker,) if payload.ticker else ())
        candidate_tickers = tuple(dict.fromkeys(requested_scope + followed_tickers))
        for ticker in candidate_tickers:
            if await dependencies.repository.count_documents(ticker) > 0:
                continue
            try:
                await dependencies.ingestion.ingest(ticker)
            except (
                KeyError,
                LookupError,
                OSError,
                RuntimeError,
                TimeoutError,
                TypeError,
                ValueError,
            ):
                continue
        result = await dependencies.agent.chat(
            user_id,
            payload.message,
            payload.ticker,
            scope_tickers=payload.tickers,
        )
        await dependencies.repository.add_conversation_message(
            ConversationMessage(
                id=uuid4().hex,
                conversation_id=conversation_id,
                role="assistant",
                text=result.answer,
                title=result.title,
                scope_tickers=payload.tickers or ((payload.ticker,) if payload.ticker else ()),
                citations=result.citations,
                created_at=datetime.now(UTC),
            )
        )
        return result.model_copy(update={"conversation_id": conversation_id})

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
