from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import HTTPException, Request, Response, status
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

from app.repositories.base import ResearchRepository
from app.settings import Settings

SESSION_COOKIE = "sentellent_session"
OAUTH_STATE_COOKIE = "sentellent_oauth_state"


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: str
    email: str
    name: str | None = None
    picture: str | None = None


class GoogleOidcService:
    AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

    def __init__(self, settings: Settings, repository: ResearchRepository) -> None:
        self._settings = settings
        self._repository = repository

    def login_url(self, response: Response) -> str:
        self._ensure_configured()
        nonce = secrets.token_urlsafe(24)
        state = jwt.encode(
            {"nonce": nonce, "iat": int(time.time()), "exp": int(time.time()) + 600},
            self._session_secret(),
            algorithm="HS256",
        )
        response.set_cookie(
            OAUTH_STATE_COOKIE,
            state,
            max_age=600,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/api/v1/auth/google/callback",
        )
        query = urlencode(
            {
                "client_id": self._settings.google_client_id,
                "redirect_uri": self._settings.google_redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "nonce": nonce,
                "access_type": "online",
                "prompt": "select_account",
            }
        )
        return f"{self.AUTHORIZATION_ENDPOINT}?{query}"

    async def callback(
        self, *, code: str, state: str, state_cookie: str | None, response: Response
    ) -> AuthenticatedUser:
        claims = self.validate_callback_state(state, state_cookie)
        token_payload = await self._exchange_code(code)
        token = token_payload.get("id_token")
        if not isinstance(token, str):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google did not return an ID token",
            )
        identity = await self._verify_token(token)
        if identity.get("nonce") != claims.get("nonce"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid OIDC nonce"
            )
        email = identity.get("email")
        subject = identity.get("sub")
        if (
            not isinstance(email, str)
            or not isinstance(subject, str)
            or not identity.get("email_verified")
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="A verified Google email is required",
            )
        name = identity.get("name")
        picture = identity.get("picture")
        user = AuthenticatedUser(
            id=subject,
            email=email,
            name=name if isinstance(name, str) else None,
            picture=picture if isinstance(picture, str) else None,
        )
        await self._repository.upsert_user(user.id, user.email, user.name, user.picture)
        session_id = secrets.token_urlsafe(32)
        expires_at = time.time() + self._settings.session_ttl_seconds
        await self._repository.create_session(
            self._session_digest(session_id), user.id, expires_at
        )
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            max_age=self._settings.session_ttl_seconds,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
        response.delete_cookie(OAUTH_STATE_COOKIE, path="/api/v1/auth/google/callback")
        return user

    def callback_rate_limit_key(self, state: str, state_cookie: str | None) -> str:
        claims = self.validate_callback_state(state, state_cookie)
        nonce = claims.get("nonce")
        if not isinstance(nonce, str) or not nonce:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OIDC nonce"
            )
        return hashlib.sha256(f"oauth-callback:{nonce}".encode()).hexdigest()

    def validate_callback_state(
        self, state: str, state_cookie: str | None
    ) -> dict[str, object]:
        self._ensure_configured()
        if not state_cookie or not hmac.compare_digest(state, state_cookie):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state"
            )
        try:
            return dict(jwt.decode(state, self._session_secret(), algorithms=["HS256"]))
        except jwt.PyJWTError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Expired or invalid OAuth state",
            ) from error

    async def current_user_id(self, request: Request) -> str:
        if self._settings.auth_mode == "demo":
            if self._settings.app_env not in {"development", "test"}:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Demo auth is disabled in production",
                )
            user_id = request.headers.get("X-User-ID") or self._settings.demo_user_id
            if not user_id or len(user_id) > 320:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                )
            return user_id
        raw_session = request.cookies.get(SESSION_COOKIE)
        if not raw_session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        user_id = await self._repository.get_session_user(
            self._session_digest(raw_session), time.time()
        )
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired"
            )
        return user_id

    async def logout(self, request: Request, response: Response) -> None:
        raw_session = request.cookies.get(SESSION_COOKIE)
        if raw_session:
            await self._repository.delete_session(self._session_digest(raw_session))
        response.delete_cookie(
            SESSION_COOKIE, path="/", httponly=True, secure=True, samesite="lax"
        )

    async def _exchange_code(self, code: str) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                self.TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": self._settings.google_client_id,
                    "client_secret": self._settings.google_client_secret,
                    "redirect_uri": self._settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Google token exchange failed",
                )
            return response.json()

    async def _verify_token(self, token: str) -> dict[str, object]:
        try:
            verified = await asyncio.to_thread(
                id_token.verify_oauth2_token,
                token,
                GoogleRequest(),
                self._settings.google_client_id,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google ID token",
            ) from error
        return dict(verified)

    def _ensure_configured(self) -> None:
        if not self._settings.google_oauth_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google OAuth is not configured",
            )

    def _session_secret(self) -> str:
        secret = self._settings.session_secret
        if secret is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google OAuth is not configured",
            )
        return secret

    @staticmethod
    def _session_digest(session_id: str) -> str:
        return hashlib.sha256(session_id.encode()).hexdigest()
