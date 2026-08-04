from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import DocumentKind, SourceDocument, canonical_source_url


def test_compare_extracts_only_requested_tickers_and_is_stable(
    client, auth_headers
) -> None:
    for ticker in ("TCS", "INFY", "RELIANCE"):
        assert (
            client.post(
                f"/api/v1/stocks/{ticker}/follow", headers=auth_headers
            ).status_code
            == 201
        )

    request = {
        "message": "Compare INFY versus TCS on valuation, leverage, and recent sentiment."
    }
    first = client.post("/api/v1/chat", headers=auth_headers, json=request)
    second = client.post("/api/v1/chat", headers=auth_headers, json=request)

    assert first.status_code == 200
    body = first.json()
    assert body["grounded"] is True
    assert body["recommendations"] == []
    assert "Infosys" in body["answer"]
    assert "Tata Consultancy Services" in body["answer"]
    assert "Reliance Industries" not in body["answer"]
    assert {"INFY", "TCS"} == {
        "INFY" if "infosys" in citation["title"].lower() else "TCS"
        for citation in body["citations"]
        if "fundamentals" in citation["title"].lower()
    }
    assert second.json()["answer"] == body["answer"]
    assert second.json()["citations"] == body["citations"]


def test_message_ticker_extraction_scopes_retrieval_without_ui_ticker(
    client, auth_headers
) -> None:
    for ticker in ("TCS", "INFY"):
        client.post(f"/api/v1/stocks/{ticker}/follow", headers=auth_headers)

    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "What is the latest news and price for INFY?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "Infosys" in body["answer"]
    assert "Tata Consultancy Services" not in body["answer"]
    assert all("tcs" not in citation["title"].lower() for citation in body["citations"])


def test_explicit_scope_tickers_override_active_ticker(client, auth_headers) -> None:
    for ticker in ("TCS", "INFY"):
        client.post(f"/api/v1/stocks/{ticker}/follow", headers=auth_headers)

    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={
            "message": "Summarize the selected companies.",
            "ticker": "RELIANCE",
            "tickers": ["TCS", "INFY"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "Tata Consultancy Services" in body["answer"]
    assert "Infosys" in body["answer"]
    assert "Reliance Industries" not in body["answer"]


def test_unrelated_prompt_is_not_answered_in_ticker_context(client, auth_headers) -> None:
    client.post("/api/v1/stocks/TCS/follow", headers=auth_headers)

    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "Write a poem for me.", "ticker": "TCS"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_kind"] == "out_of_scope"
    assert body["grounded"] is True
    assert body["citations"] == []
    assert "outside Artha's research scope" in body["answer"]
    assert "TCS" not in body["answer"]


async def test_cross_ticker_shared_story_has_one_citation(container) -> None:
    user_id = "comparison@example.com"
    for ticker in ("TCS", "INFY"):
        await container.ingestion.ingest(ticker)
        await container.repository.follow_stock(user_id, ticker)
        shared = SourceDocument.create(
            ticker=ticker,
            kind=DocumentKind.NEWS,
            title="TCS and Infosys win a shared digital services contract",
            url="https://news.example.test/shared-contract?utm_source=rss",
            content="TCS and Infosys both won the digital services contract; reporting is positive.",
            published_at=datetime(2026, 8, 3, tzinfo=UTC),
            sentiment=0.6,
            mentioned_tickers=("INFY", "TCS"),
        )
        embedding = await container.embedder.embed(shared.content)
        await container.repository.insert_document(shared, embedding)

    result = await container.agent.chat(user_id, "Compare TCS and INFY latest news")
    canonical_urls = [canonical_source_url(item.url) for item in result.citations]

    assert result.grounded is True
    assert canonical_urls.count("https://news.example.test/shared-contract") == 1
    assert len(canonical_urls) == len(set(canonical_urls))
