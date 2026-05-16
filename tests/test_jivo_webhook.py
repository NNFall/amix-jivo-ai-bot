from fastapi.testclient import TestClient

from database.db import session_scope
from database.models import Chat, Handoff, JivoEvent, Message, Product
from main import create_application


def build_client():
    app = create_application()
    return TestClient(app)


def test_jivo_webhook_rejects_invalid_token(isolated_app_env) -> None:
    with build_client() as client:
        response = client.post(
            "/webhooks/jivo/wrong-token",
            json={"id": "event-1", "event": "CLIENT_MESSAGE", "chat_id": "chat-1", "client_id": "client-1"},
        )

    assert response.status_code == 403


def test_jivo_webhook_deduplicates_event(isolated_app_env) -> None:
    payload = {
        "id": "event-1",
        "event": "CLIENT_MESSAGE",
        "chat_id": "chat-1",
        "client_id": "client-1",
        "message": {"type": "TEXT", "text": "Есть ли AB-123?"},
    }

    with build_client() as client:
        first_response = client.post("/webhooks/jivo/test-token", json=payload)
        second_response = client.post("/webhooks/jivo/test-token", json=payload)

    assert first_response.status_code == 200
    assert first_response.json() == {"ok": True, "accepted": True, "duplicate": False}
    assert second_response.status_code == 200
    assert second_response.json() == {"ok": True, "accepted": False, "duplicate": True}

    with session_scope() as session:
        events = session.query(JivoEvent).all()

    assert len(events) == 1
    assert events[0].status == "processed"


def test_jivo_webhook_processes_product_lookup_flow(isolated_app_env) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="1",
                article="AB-123",
                normalized_article="AB123",
                free_stock=5,
                unit="шт.",
                retail_price=99.5,
                corporate_price=88,
                raw_payload={},
            )
        )

    payload = {
        "id": "event-2",
        "event": "CLIENT_MESSAGE",
        "chat_id": "chat-lookup",
        "client_id": "client-lookup",
        "site_id": "123456",
        "agents_online": True,
        "sender": {
            "id": 123,
            "name": "Test Client",
            "url": "https://amix.local/catalog",
            "has_contacts": True,
        },
        "channel": {"id": "widget-1", "type": "widget"},
        "message": {"type": "TEXT", "text": "Нужен артикул AB-123"},
    }

    with build_client() as client:
        response = client.post("/webhooks/jivo/test-token", json=payload)

    assert response.status_code == 200

    with session_scope() as session:
        messages = session.query(Message).order_by(Message.id.asc()).all()

    assert len(messages) == 2
    assert messages[0].sender_role == "client"
    assert "AB-123" in messages[0].text
    assert messages[1].sender_role == "bot"
    assert "Артикул AB-123 найден." in messages[1].text


def test_jivo_webhook_handoff_flow_creates_handoff_record(isolated_app_env) -> None:
    payload = {
        "id": "event-3",
        "event": "CLIENT_MESSAGE",
        "chat_id": "chat-handoff",
        "client_id": "client-handoff",
        "message": {"type": "TEXT", "text": "Мне нужен менеджер для подбора"},
    }

    with build_client() as client:
        response = client.post("/webhooks/jivo/test-token", json=payload)

    assert response.status_code == 200

    with session_scope() as session:
        handoffs = session.query(Handoff).all()
        messages = session.query(Message).order_by(Message.id.asc()).all()

    assert len(handoffs) == 1
    assert handoffs[0].reason == "client_requested_manager"
    assert len(messages) == 2
    assert messages[1].sender_role == "bot"
    assert "Передаю вопрос менеджеру." in messages[1].text


def test_jivo_webhook_agent_joined_marks_chat_as_terminal(isolated_app_env) -> None:
    payload = {
        "id": "event-4",
        "event": "AGENT_JOINED",
        "chat_id": "chat-agent",
        "client_id": "client-agent",
        "sender": {"id": "agent-1", "name": "Operator"},
    }

    with build_client() as client:
        response = client.post("/webhooks/jivo/test-token", json=payload)

    assert response.status_code == 200

    with session_scope() as session:
        chat = session.query(Chat).filter(Chat.external_chat_id == "chat-agent").one()
        messages = session.query(Message).all()

    assert chat.status == "agent_joined"
    assert messages == []
