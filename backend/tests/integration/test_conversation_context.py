from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import ConversationMessage, ResearchConversation


def test_follow_up_resolves_to_prior_user_scope(client, auth_headers) -> None:
    for ticker in ("TCS", "INFY"):
        client.post(f"/api/v1/stocks/{ticker}/follow", headers=auth_headers)

    first = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "What is the latest news for TCS?"},
    )
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "What about that?", "conversation_id": conversation_id},
    )

    assert second.status_code == 200
    assert "Tata Consultancy Services" in second.json()["answer"]
    assert "Infosys" not in second.json()["answer"]


def test_chat_passes_only_latest_eight_messages_to_agent(container, client, auth_headers, monkeypatch) -> None:
    conversation_id = "bounded-context"
    now = datetime(2026, 8, 4, tzinfo=UTC)
    awaitable = container.repository.create_conversation(
        ResearchConversation(
            id=conversation_id,
            user_id="investor@example.com",
            title="Context",
            created_at=now,
            updated_at=now,
        )
    )
    import asyncio

    asyncio.run(awaitable)
    for index in range(10):
        asyncio.run(
            container.repository.add_conversation_message(
                ConversationMessage(
                    id=f"message-{index}",
                    conversation_id=conversation_id,
                    role="user",
                    text=f"Question {index}",
                    created_at=now,
                )
            )
        )

    captured: dict[str, object] = {}
    original_chat = container.agent.chat

    async def capture_chat(*args, **kwargs):
        captured["history"] = kwargs["conversation_history"]
        return await original_chat(*args, **kwargs)

    monkeypatch.setattr(container.agent, "chat", capture_chat)
    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "What about that?", "conversation_id": conversation_id},
    )

    assert response.status_code == 200
    history = captured["history"]
    assert len(history) == 8
    assert history[0].id == "message-2"
    assert history[-1].id == "message-9"


def test_chat_rejects_conversation_owned_by_another_user(client, auth_headers, container) -> None:
    import asyncio

    asyncio.run(
        container.repository.create_conversation(
            ResearchConversation(
                id="foreign-conversation",
                user_id="other@example.com",
                title="Private",
                created_at=datetime(2026, 8, 4, tzinfo=UTC),
                updated_at=datetime(2026, 8, 4, tzinfo=UTC),
            )
        )
    )

    response = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={
            "message": "What about that?",
            "conversation_id": "foreign-conversation",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found"
