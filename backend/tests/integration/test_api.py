from __future__ import annotations

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import jwt
from fastapi.testclient import TestClient

from app.api import create_app
from app.container import build_container
from app.settings import Settings


def test_health_is_public(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_liveness_does_not_depend_on_repository_health(client, container) -> None:
    async def unhealthy() -> bool:
        return False

    container.repository.healthcheck = unhealthy
    assert client.get("/health").status_code == 200
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503
    assert client.get("/api/health").status_code == 503


def test_protected_routes_require_identity(client) -> None:
    response = client.get("/api/v1/persona")
    assert response.status_code == 401


def test_logout_returns_no_content_and_clears_cookie(client) -> None:
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert "sentellent_session" in response.headers.get("set-cookie", "")


def test_unfollow_removes_stock_from_user_watchlist(client, auth_headers) -> None:
    followed = client.post("/api/v1/stocks/TCS/follow", headers=auth_headers)
    assert followed.status_code == 201

    removed = client.delete("/api/v1/stocks/TCS/follow", headers=auth_headers)
    assert removed.status_code == 200
    assert removed.json() == {"ticker": "TCS", "followed": False}
    assert client.get("/api/v1/stocks", headers=auth_headers).json() == []


def test_versioned_sources_and_ingest_routes_are_available(client, auth_headers) -> None:
    followed = client.post("/api/v1/stocks/TCS/follow", headers=auth_headers)
    assert followed.status_code == 201
    assert client.get("/api/v1/sources?ticker=TCS", headers=auth_headers).status_code == 200
    assert client.post(
        "/api/v1/stocks/TCS/ingest", headers=auth_headers
    ).status_code == 200


def test_follow_stock_and_grounded_chat_flow(client, auth_headers) -> None:
    followed = client.post("/api/v1/stocks/TCS/follow", headers=auth_headers)
    assert followed.status_code == 201
    assert followed.json()["ticker"] == "TCS"
    assert followed.json()["stock"]["ticker"] == "TCS"
    assert float(followed.json()["stock"]["price_inr"]) > 0
    assert followed.json()["ingestion"]["inserted"] > 0

    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={
            "message": "What's the price and sentiment on TCS this week?",
            "ticker": "TCS",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "INR" in body["answer"]
    assert "[1]" in body["answer"]
    assert body["citations"][0]["url"].startswith("https://")
    assert body["grounded"] is True


def test_recent_changes_question_returns_news_evidence(client, auth_headers) -> None:
    followed = client.post("/api/v1/stocks/TCS/follow", headers=auth_headers)
    assert followed.status_code == 201
    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "What changed this week for TCS?", "ticker": "TCS"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "reporting" in body["answer"].lower()
    assert len(body["citations"]) >= 1


def test_follow_preserves_bse_exchange_and_returns_hydrated_stock(
    client, auth_headers
) -> None:
    response = client.post("/api/v1/stocks/TCS.BO/follow", headers=auth_headers)
    assert response.status_code == 201
    assert response.json()["ticker"] == "TCS"
    assert response.json()["stock"]["exchange"] == "BSE"


def test_chat_updates_persona_and_recommends_from_followed_universe(
    client, auth_headers
) -> None:
    for ticker in ("TCS", "RELIANCE", "ITC"):
        assert (
            client.post(
                f"/api/v1/stocks/{ticker}/follow", headers=auth_headers
            ).status_code
            == 201
        )

    learned = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={
            "message": "I am conservative, dividend focused, and avoid high debt companies."
        },
    )
    assert learned.status_code == 200
    assert learned.json()["persona_updated"] is True

    persona = client.get("/api/v1/persona", headers=auth_headers).json()
    assert persona["risk_tolerance"] == "conservative"
    assert persona["avoid_high_debt"] is True

    recommendation = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "Recommend stocks for my profile."},
    )
    assert recommendation.status_code == 200
    assert recommendation.json()["grounded"] is True
    assert recommendation.json()["recommendations"]


def test_plain_language_profile_question_returns_followed_recommendations(
    client, auth_headers
) -> None:
    for ticker in ("TCS", "RELIANCE"):
        assert (
            client.post(
                f"/api/v1/stocks/{ticker}/follow", headers=auth_headers
            ).status_code
            == 201
        )

    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "Which followed company best fits my profile?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"]
    assert body["citations"]


def test_persona_patch_validates_and_updates_fields(client, auth_headers) -> None:
    response = client.patch(
        "/api/v1/persona",
        headers=auth_headers,
        json={"risk_tolerance": "aggressive", "preferred_sectors": ["IT", "Banking"]},
    )
    assert response.status_code == 200
    assert response.json()["risk_tolerance"] == "aggressive"


def test_invalid_ticker_is_rejected_at_boundary(client, auth_headers) -> None:
    response = client.post("/api/v1/stocks/INVALID%3BDROP/follow", headers=auth_headers)
    assert response.status_code == 422


def test_google_oauth_config_is_env_driven(client) -> None:
    response = client.get("/api/v1/auth/google/config")
    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert "client_secret" not in response.text.lower()


def test_chat_rate_limit_returns_retry_after() -> None:
    container = build_container(
        Settings(app_env="test", auth_mode="demo", rate_limit_chat_requests=1)
    )
    with TestClient(create_app(container)) as client:
        headers = {"X-User-ID": "limited@example.com"}
        payload = {"message": "What should I know?"}
        assert (
            client.post("/api/v1/chat", headers=headers, json=payload).status_code
            == 200
        )
        limited = client.post("/api/v1/chat", headers=headers, json=payload)
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) >= 1


def test_google_oidc_flow_validates_state_nonce_and_creates_secure_session() -> None:
    session_key = "test-session-key-" + "x" * 32
    settings = Settings(
        app_env="test",
        auth_mode="google",
        google_client_id="test-client.apps.googleusercontent.com",
        google_client_secret="environment-only-secret",
        session_secret=session_key,
        google_redirect_uri="https://api.example.test/api/v1/auth/google/callback",
        auth_success_url="https://app.example.test",
    )
    container = build_container(settings)
    with TestClient(
        create_app(container), base_url="https://api.example.test"
    ) as client:
        login = client.get("/api/v1/auth/google/login", follow_redirects=False)
        assert login.status_code == 307
        query = parse_qs(urlsplit(login.headers["location"]).query)
        state_value = query["state"][0]
        claims = jwt.decode(state_value, session_key, algorithms=["HS256"])
        container.auth._exchange_code = AsyncMock(
            return_value={"id_token": "signed-google-token"}
        )
        container.auth._verify_token = AsyncMock(
            return_value={
                "sub": "google-user-123",
                "email": "reviewer@example.com",
                "email_verified": True,
                "name": "Reviewer",
                "picture": "https://example.test/avatar.png",
                "nonce": claims["nonce"],
            }
        )
        callback = client.get(
            "/api/v1/auth/google/callback",
            params={"code": "authorization-code", "state": state_value},
            follow_redirects=False,
        )
        assert callback.status_code == 303
        cookie = callback.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
        assert "environment-only-secret" not in login.text + callback.text
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "reviewer@example.com"


def test_google_oidc_callback_rejects_state_mismatch() -> None:
    container = build_container(
        Settings(
            app_env="test",
            auth_mode="google",
            google_client_id="client",
            google_client_secret="secret",
            session_secret="another-random-session-secret-long-enough",
        )
    )
    with TestClient(
        create_app(container), base_url="https://api.example.test"
    ) as client:
        client.get("/api/v1/auth/google/login", follow_redirects=False)
        response = client.get(
            "/api/v1/auth/google/callback",
            params={"code": "authorization-code", "state": "attacker-state"},
            follow_redirects=False,
        )
        assert response.status_code == 400


def test_bogus_oauth_callbacks_cannot_exhaust_valid_state_and_nonces_are_isolated() -> (
    None
):
    session_key = "test-oauth-key-" + "x" * 32
    container = build_container(
        Settings(
            app_env="test",
            auth_mode="google",
            google_client_id="client",
            google_client_secret="secret",
            session_secret=session_key,
            rate_limit_oauth_requests=1,
        )
    )
    app = create_app(container)
    with (
        TestClient(app, base_url="https://api.example.test") as first_client,
        TestClient(app, base_url="https://api.example.test") as second_client,
    ):
        first_login = first_client.get(
            "/api/v1/auth/google/login", follow_redirects=False
        )
        second_login = second_client.get(
            "/api/v1/auth/google/login", follow_redirects=False
        )
        first_state = parse_qs(urlsplit(first_login.headers["location"]).query)[
            "state"
        ][0]
        second_state = parse_qs(urlsplit(second_login.headers["location"]).query)[
            "state"
        ][0]
        first_nonce = jwt.decode(first_state, session_key, algorithms=["HS256"])["nonce"]
        second_nonce = jwt.decode(second_state, session_key, algorithms=["HS256"])["nonce"]

        async def exchange(code: str):
            return {"id_token": code}

        async def verify(token: str):
            nonce = first_nonce if token == "first-code" else second_nonce
            suffix = "first" if token == "first-code" else "second"
            return {
                "sub": f"google-{suffix}",
                "email": f"{suffix}@example.test",
                "email_verified": True,
                "nonce": nonce,
            }

        container.auth._exchange_code = exchange
        container.auth._verify_token = verify
        for _ in range(3):
            bogus = first_client.get(
                "/api/v1/auth/google/callback",
                params={"code": "bad", "state": "attacker-state"},
                follow_redirects=False,
            )
            assert bogus.status_code == 400

        first_callback = first_client.get(
            "/api/v1/auth/google/callback",
            params={"code": "first-code", "state": first_state},
            follow_redirects=False,
        )
        second_callback = second_client.get(
            "/api/v1/auth/google/callback",
            params={"code": "second-code", "state": second_state},
            follow_redirects=False,
        )
        assert first_callback.status_code == 303
        assert second_callback.status_code == 303


def test_production_responses_include_hsts() -> None:
    container = build_container(
        Settings(
            app_env="production",
            database_url="sqlite+aiosqlite:///:memory:",
        )
    )
    with TestClient(
        create_app(container), base_url="https://api.example.test"
    ) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["Strict-Transport-Security"].startswith("max-age=63072000")
