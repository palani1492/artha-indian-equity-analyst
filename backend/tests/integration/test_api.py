from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.container import build_container
from app.domain.models import ConversationMessage, InvestorPersona, ResearchConversation
from app.settings import Settings


def test_health_is_public(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_ticker_search_is_public_and_returns_directory_metadata(client) -> None:
    response = client.get("/api/v1/tickers/search", params={"q": "inf"})

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "bundled-indian-equity-directory"
    assert body["source_metadata"]["refresh_policy"] == "manual bundle update"
    assert body["suggestions"]
    assert body["suggestions"][0] == {
        "ticker": "INFY",
        "company_name": "Infosys",
        "sector": "IT services",
        "exchange": "NSE",
        "bse_id": "500209",
    }


@pytest.mark.parametrize("query", ("", "i", "x" * 31))
def test_ticker_search_validates_query_length(client, query: str) -> None:
    response = client.get("/api/v1/tickers/search", params={"q": query})

    assert response.status_code == 422


def test_ticker_search_filters_exchange_and_matches_company_name(client) -> None:
    response = client.get(
        "/api/v1/tickers/search", params={"q": "bank", "exchange": "BSE"}
    )

    assert response.status_code == 200
    suggestions = response.json()["suggestions"]
    assert suggestions
    assert all(item["exchange"] == "BSE" for item in suggestions)
    assert any(item["ticker"] == "HDFCBANK" for item in suggestions)


@pytest.mark.parametrize(
    ("query", "ticker", "company_name"),
    (
        ("mahindra", "M&M", "Mahindra & Mahindra"),
        ("m&m", "M&M", "Mahindra & Mahindra"),
        ("infosys", "INFY", "Infosys"),
        ("tata consultancy services", "TCS", "Tata Consultancy Services"),
        ("hdfc bank", "HDFCBANK", "HDFC Bank"),
        ("state bank of india", "SBIN", "State Bank of India"),
        ("reliance industries", "RELIANCE", "Reliance Industries"),
    ),
)
def test_ticker_search_supports_company_names_and_aliases(
    client, query: str, ticker: str, company_name: str
) -> None:
    response = client.get("/api/v1/tickers/search", params={"q": query})

    assert response.status_code == 200
    suggestions = response.json()["suggestions"]
    assert suggestions[0]["ticker"] == ticker
    assert suggestions[0]["company_name"] == company_name
    assert all("aliases" not in suggestion for suggestion in suggestions)


def test_ticker_search_ranks_exact_ticker_and_field_prefix_before_substrings(
    client,
) -> None:
    response = client.get("/api/v1/tickers/search", params={"q": "bank"})

    assert response.status_code == 200
    suggestions = response.json()["suggestions"]
    assert suggestions[0]["ticker"] == "BANKBARODA"
    assert suggestions[0]["company_name"] == "Bank of Baroda"


def test_ticker_search_rejects_unknown_exchange(client) -> None:
    response = client.get(
        "/api/v1/tickers/search", params={"q": "it", "exchange": "NYSE"}
    )

    assert response.status_code == 422


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


def test_research_conversations_persist_scoped_cited_chat(client, auth_headers) -> None:
    created = client.post(
        "/api/v1/conversations", headers=auth_headers, json={"title": "TCS thesis"}
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={
            "message": "What changed for TCS?",
            "ticker": "TCS",
            "conversation_id": conversation_id,
        },
    )
    assert response.status_code == 200
    assert response.json()["conversation_id"] == conversation_id

    messages = client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=auth_headers
    )
    assert messages.status_code == 200
    assert [message["role"] for message in messages.json()] == ["user", "assistant"]
    assert messages.json()[1]["scope_tickers"] == ["TCS"]
    assert messages.json()[1]["citations"]


def test_conversation_title_patch_is_validated_and_user_owned(client, auth_headers) -> None:
    created = client.post(
        "/api/v1/conversations", headers=auth_headers, json={"title": "Original"}
    )
    conversation_id = created.json()["id"]

    renamed = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        headers=auth_headers,
        json={"title": "  Renamed thesis  "},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Renamed thesis"

    assert client.patch(
        f"/api/v1/conversations/{conversation_id}",
        headers={"X-User-ID": "other@example.com"},
        json={"title": "No access"},
    ).status_code == 404
    assert client.patch(
        f"/api/v1/conversations/{conversation_id}",
        headers=auth_headers,
        json={"title": " "},
    ).status_code == 422
    assert client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"title": "Unauthenticated"},
    ).status_code == 401


def test_notes_are_user_owned_and_validated(client, auth_headers) -> None:
    payload = {
        "title": "TCS thesis",
        "body": "Check demand commentary against the next filing.",
        "scope_tickers": ["TCS"],
        "citations": [
            {
                "index": 1,
                "document_id": "doc-1",
                "title": "TCS filing",
                "url": "https://example.com/tcs",
            }
        ],
    }
    created = client.post("/api/v1/notes", headers=auth_headers, json=payload)
    assert created.status_code == 201
    note_id = created.json()["id"]
    assert client.get("/api/v1/notes", headers=auth_headers).json()[0]["user_id"] == "investor@example.com"
    assert client.get("/api/v1/notes", headers={"X-User-ID": "other@example.com"}).json() == []
    assert client.patch(
        f"/api/v1/notes/{note_id}", headers={"X-User-ID": "other@example.com"}, json=payload
    ).status_code == 404
    assert client.post("/api/v1/notes", headers=auth_headers, json={"title": " ", "body": "x"}).status_code == 422


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


def test_versioned_sources_and_ingest_routes_are_available(
    client, auth_headers
) -> None:
    followed = client.post("/api/v1/stocks/TCS/follow", headers=auth_headers)
    assert followed.status_code == 201
    assert (
        client.get("/api/v1/sources?ticker=TCS", headers=auth_headers).status_code
        == 200
    )
    assert (
        client.post("/api/v1/stocks/TCS/ingest", headers=auth_headers).status_code
        == 200
    )
    facts = client.get("/api/v1/stocks/TCS/graph-facts", headers=auth_headers)
    assert facts.status_code == 200
    assert all(fact["source_url"].startswith("https://") for fact in facts.json())


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


def test_refresh_route_rehydrates_every_followed_quote_and_compacts_sources(
    client, auth_headers
) -> None:
    for ticker in ("TCS", "INFY"):
        assert (
            client.post(
                f"/api/v1/stocks/{ticker}/follow", headers=auth_headers
            ).status_code
            == 201
        )
    refreshed = client.post("/api/v1/refresh", headers=auth_headers)
    assert refreshed.status_code == 200
    body = refreshed.json()
    assert {stock["ticker"] for stock in body["stocks"]} == {"TCS", "INFY"}
    assert {result["ticker"] for result in body["results"]} == {"TCS", "INFY"}
    sources = client.get("/api/v1/sources?ticker=TCS", headers=auth_headers).json()
    assert len(sources) == 2


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
    assert "Fit reasons:" not in recommendation.json()["answer"]


def test_memory_update_is_not_treated_as_stock_research(client, auth_headers) -> None:
    assert client.post("/api/v1/stocks/INFY/follow", headers=auth_headers).status_code == 201

    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={
            "message": "I am a conservative investor who prefers low debt and durable cash flows. Remember this.",
            "ticker": "INFY",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["persona_updated"] is True
    assert body["answer_kind"] == "memory_update"
    assert body["title"] == "Memory updated"
    assert body["citations"] == []
    assert "updated your investor memory" in body["answer"].lower()
    assert "infosys" not in body["answer"].lower()
    assert body["persona"]["risk_tolerance"] == "conservative"
    assert "Low leverage" in body["persona"]["priorities"]


def test_memory_question_answers_from_stored_profile(client, auth_headers) -> None:
    learned = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={
            "message": "I am conservative and prefer low debt, dividends, and durable cash flows. Remember this."
        },
    )
    assert learned.status_code == 200

    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "What kind of investor am I?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_kind"] == "memory_question"
    assert body["citations"] == []
    assert "conservative investor" in body["answer"].lower()
    assert "low leverage" in body["answer"].lower()


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


def test_starter_profile_question_returns_followed_recommendations(
    client, auth_headers
) -> None:
    for ticker in ("TCS", "INFY"):
        assert (
            client.post(
                f"/api/v1/stocks/{ticker}/follow", headers=auth_headers
            ).status_code
            == 201
        )

    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "Find a fit for my profile"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"]
    assert body["citations"]


def test_complex_question_filters_followed_universe_and_total_budget(
    client, auth_headers
) -> None:
    for ticker in ("TCS", "INFY", "RELIANCE"):
        assert client.post(
            f"/api/v1/stocks/{ticker}/follow", headers=auth_headers
        ).status_code == 201

    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={
            "message": "find me 1 to 5 technology stocks within INR 20000 that match my investor profile"
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_kind"] == "constrained_recommendation"
    assert body["grounded"] is True
    assert {item["stock"]["ticker"] for item in body["recommendations"]} == {
        "TCS",
        "INFY",
    }
    assert sum(float(item["stock"]["price_inr"]) for item in body["recommendations"]) <= 20000
    assert body["metadata"] == {
        "requested_min_count": 1,
        "requested_max_count": 5,
        "budget_inr": "20000",
        "sector": "IT",
        "total_selected_inr": "5967.80",
        "universe": "followed/indexed",
    }
    assert body["citations"]
    assert "Conclusion:" in body["answer"]
    assert "Risks:" in body["answer"]
    assert "Data limitations:" in body["answer"]


def test_complex_question_states_limitation_when_followed_data_is_insufficient(
    client, auth_headers
) -> None:
    assert client.post("/api/v1/stocks/TCS/follow", headers=auth_headers).status_code == 201

    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "find 3 to 5 technology stocks within INR 1000"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_kind"] == "constrained_recommendation"
    assert body["grounded"] is True
    assert body["recommendations"] == []
    assert "Only 0 of the requested minimum 3 stocks fit" in body["answer"]
    assert body["metadata"]["universe"] == "followed/indexed"


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


def test_admin_endpoints_authorize_only_allowlisted_persisted_user(container) -> None:
    container.settings.admin_emails = ("admin@example.com",)
    asyncio.run(
        container.repository.upsert_user("admin-id", "admin@example.com", "Admin", None)
    )
    asyncio.run(container.repository.upsert_user("user-id", "user@example.com", "User", None))
    asyncio.run(container.repository.follow_stock("user-id", "TCS"))
    asyncio.run(
        container.repository.save_persona(
            InvestorPersona(user_id="user-id", style="Reset me"), (1.0,)
        )
    )
    with TestClient(create_app(container)) as admin_client:
        assert admin_client.get(
            "/api/v1/admin/users", headers={"X-User-ID": "user-id"}
        ).status_code == 403
        listed = admin_client.get(
            "/api/v1/admin/users", headers={"X-User-ID": "admin-id"}
        )
        assert listed.status_code == 200
        assert {user["id"] for user in listed.json()} == {"admin-id", "user-id"}

        reset = admin_client.post(
            "/api/v1/admin/users/user-id/reset-profile",
            headers={"X-User-ID": "admin-id"},
        )
        assert reset.status_code == 200
        assert asyncio.run(container.repository.list_followed_tickers("user-id")) == ()
        assert asyncio.run(container.repository.get_persona("user-id")).style != "Reset me"


def test_admin_endpoints_do_not_trust_frontend_email_and_validate_target(container) -> None:
    container.settings.admin_emails = ("admin@example.com",)
    asyncio.run(
        container.repository.upsert_user("admin-id", "admin@example.com", "Admin", None)
    )
    with TestClient(create_app(container)) as admin_client:
        assert admin_client.get(
            "/api/v1/admin/users", headers={"X-User-ID": "admin@example.com"}
        ).status_code == 401
        assert admin_client.post(
            "/api/v1/admin/users/missing/reset-profile",
            headers={"X-User-ID": "admin-id"},
        ).status_code == 404
        assert admin_client.post(
            "/api/v1/admin/users/%20/reset-profile",
            headers={"X-User-ID": "admin-id"},
        ).status_code == 422


def test_admin_controls_delete_conversations_reset_follows_and_protect_admin(container) -> None:
    container.settings.admin_emails = ("admin@example.com",)
    now = datetime.now(UTC)
    asyncio.run(container.repository.upsert_user("admin-id", "admin@example.com", "Admin", None))
    asyncio.run(container.repository.upsert_user("user-id", "user@example.com", "User", None))
    asyncio.run(container.repository.follow_stock("user-id", "TCS"))
    conversation = ResearchConversation(
        id="conversation-1", user_id="user-id", title="Research", created_at=now, updated_at=now
    )
    asyncio.run(container.repository.create_conversation(conversation))
    asyncio.run(container.repository.add_conversation_message(
        ConversationMessage(
            id="message-1", conversation_id=conversation.id, role="user", text="Review TCS",
            scope_tickers=("TCS",), created_at=now,
        )
    ))

    with TestClient(create_app(container)) as admin_client:
        assert admin_client.post(
            "/api/v1/admin/users/user-id/reset-follows", headers={"X-User-ID": "user-id"}
        ).status_code == 403
        reset_follows = admin_client.post(
            "/api/v1/admin/users/user-id/reset-follows", headers={"X-User-ID": "admin-id"}
        )
        assert reset_follows.status_code == 200
        assert reset_follows.json()["message"] == "Followed stocks reset for user user-id"
        assert asyncio.run(container.repository.list_followed_tickers("user-id")) == ()

        deleted = admin_client.delete(
            "/api/v1/admin/users/user-id/conversations", headers={"X-User-ID": "admin-id"}
        )
        assert deleted.status_code == 200
        assert "messages deleted" in deleted.json()["message"]
        assert asyncio.run(container.repository.list_conversations("user-id")) == ()
        assert asyncio.run(
            container.repository.list_conversation_messages("user-id", conversation.id)
        ) == ()

        self_target = admin_client.post(
            "/api/v1/admin/users/admin-id/reset-follows", headers={"X-User-ID": "admin-id"}
        )
        assert self_target.status_code == 409


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("post", "/api/v1/admin/users/user-id/reset-profile"),
        ("post", "/api/v1/admin/users/user-id/reset-follows"),
        ("delete", "/api/v1/admin/users/user-id/conversations"),
    ),
)
def test_all_admin_mutations_reject_non_admins(container, method: str, path: str) -> None:
    container.settings.admin_emails = ("admin@example.com",)
    asyncio.run(container.repository.upsert_user("user-id", "user@example.com", "User", None))

    with TestClient(create_app(container)) as admin_client:
        response = getattr(admin_client, method)(path, headers={"X-User-ID": "user-id"})

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "suffix"),
    (
        ("post", "reset-profile"),
        ("post", "reset-follows"),
        ("delete", "conversations"),
    ),
)
def test_all_admin_mutations_reject_missing_users(
    container, method: str, suffix: str
) -> None:
    container.settings.admin_emails = ("admin@example.com",)
    asyncio.run(
        container.repository.upsert_user("admin-id", "admin@example.com", "Admin", None)
    )

    with TestClient(create_app(container)) as admin_client:
        response = getattr(admin_client, method)(
            f"/api/v1/admin/users/missing/{suffix}", headers={"X-User-ID": "admin-id"}
        )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("method", "suffix"),
    (
        ("post", "reset-profile"),
        ("post", "reset-follows"),
        ("delete", "conversations"),
    ),
)
def test_all_admin_mutations_protect_authenticated_admin(
    container, method: str, suffix: str
) -> None:
    container.settings.admin_emails = ("admin@example.com",)
    asyncio.run(
        container.repository.upsert_user("admin-id", "admin@example.com", "Admin", None)
    )

    with TestClient(create_app(container)) as admin_client:
        response = getattr(admin_client, method)(
            f"/api/v1/admin/users/admin-id/{suffix}", headers={"X-User-ID": "admin-id"}
        )

    assert response.status_code == 409


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
        first_nonce = jwt.decode(first_state, session_key, algorithms=["HS256"])[
            "nonce"
        ]
        second_nonce = jwt.decode(second_state, session_key, algorithms=["HS256"])[
            "nonce"
        ]

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
