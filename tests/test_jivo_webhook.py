import time

from fastapi.testclient import TestClient

from database.db import session_scope
from database.models import Chat, Handoff, JivoEvent, Message, Product
from jivo.client import JivoClient
from llm.openai_client import LLMTurnResult, OpenAIService, ToolCall
from main import create_application


def build_client():
    app = create_application()
    return TestClient(app)


def wait_for_db(predicate, timeout: float = 3.0, interval: float = 0.05):
    deadline = time.time() + timeout
    last_value = None
    while time.time() < deadline:
        with session_scope() as session:
            last_value = predicate(session)
        if last_value:
            return last_value
        time.sleep(interval)
    return last_value


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
    assert events[0].status == "processing"


def test_jivo_webhook_retries_a_previously_failed_event(
    isolated_app_env,
    monkeypatch,
) -> None:
    payload = {
        "id": "event-retry",
        "event": "CLIENT_MESSAGE",
        "chat_id": "chat-retry",
        "client_id": "client-retry",
        "message": {"type": "TEXT", "text": "Проверьте товар"},
    }
    with session_scope() as session:
        session.add(
            JivoEvent(
                external_event_id=payload["id"],
                external_chat_id=payload["chat_id"],
                external_client_id=payload["client_id"],
                event_type=payload["event"],
                status="failed",
                error_text="temporary error",
                payload=payload,
            )
        )

    processed: list[int] = []
    monkeypatch.setattr("api.jivo_webhook.process_event_record", processed.append)

    with build_client() as client:
        response = client.post("/webhooks/jivo/test-token", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "accepted": True, "duplicate": False}
    assert len(processed) == 1
    with session_scope() as session:
        event = session.query(JivoEvent).one()
        assert event.status == "received"
        assert event.error_text is None


def test_jivo_webhook_processes_model_selected_product_lookup_flow(
    isolated_app_env,
    monkeypatch,
) -> None:
    monkeypatch.setattr(OpenAIService, "_is_enabled", lambda self: True)
    monkeypatch.setattr(JivoClient, "send_text_message", lambda self, event, text: True)

    def fake_run_messages(self, *, messages, tools=None, tool_choice="auto"):
        assert [tool["function"]["name"] for tool in tools] == [
            "search_products",
            "handoff_to_manager",
        ]
        assert tool_choice == "auto"
        if messages[-1]["role"] == "tool":
            return LLMTurnResult(text="Да, товар AB-123 найден.", tool_calls=[])
        return LLMTurnResult(
            text=None,
            tool_calls=[
                ToolCall(
                    name="search_products",
                    arguments={"queries": [{"query": "AB-123"}]},
                    call_id="call_product_lookup",
                )
            ],
        )

    monkeypatch.setattr(OpenAIService, "run_messages", fake_run_messages)
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

    messages = wait_for_db(
        lambda session: session.query(Message).order_by(Message.id.asc()).all()
        if session.query(Message).count() >= 4
        else None
    )

    assert len(messages) == 4
    assert messages[0].sender_role == "client"
    assert "AB-123" in messages[0].text
    assert [message.sender_role for message in messages] == ["client", "assistant_tool_call", "tool", "bot"]
    assert messages[1].payload["source"] == "llm_tool_call"
    assert messages[2].payload["source"] == "tool_result"
    assert "AB-123 найден" in messages[3].text
    assert "5 шт" not in messages[3].text


def test_jivo_webhook_handoff_flow_creates_handoff_record(isolated_app_env, monkeypatch) -> None:
    monkeypatch.setattr(OpenAIService, "_is_enabled", lambda self: True)
    monkeypatch.setattr(JivoClient, "invite_agent", lambda self, event, reason: True)
    monkeypatch.setattr(JivoClient, "send_text_message", lambda self, event, text: True)

    def fake_run_messages(self, *, messages, tools=None, tool_choice="auto"):
        return LLMTurnResult(
            text=None,
            tool_calls=[
                ToolCall(
                    name="handoff_to_manager",
                    arguments={
                        "reason": "client_requested_manager",
                        "summary": "Клиент попросил подключить менеджера для подбора.",
                        "customer_message": "Передаю вопрос менеджеру. Он подключится к диалогу.",
                    },
                    call_id="call_handoff",
                )
            ],
        )

    monkeypatch.setattr(OpenAIService, "run_messages", fake_run_messages)
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

    handoffs, messages = wait_for_db(
        lambda session: (
            session.query(Handoff).all(),
            session.query(Message).order_by(Message.id.asc()).all(),
        )
        if session.query(Handoff).count() >= 1 and session.query(Message).count() >= 4
        else None
    )

    assert len(handoffs) == 1
    assert handoffs[0].reason == "client_requested_manager"
    assert [message.sender_role for message in messages] == ["client", "assistant_tool_call", "tool", "bot"]
    assert messages[1].payload["tool_calls"][0]["function"]["name"] == "handoff_to_manager"
    assert messages[2].payload["tool_name"] == "handoff_to_manager"
    assert "Передаю вопрос менеджеру." in messages[3].text


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


def test_non_client_event_does_not_reactivate_chat_after_agent_joined(isolated_app_env) -> None:
    agent_joined = {
        "id": "event-agent-terminal",
        "event": "AGENT_JOINED",
        "chat_id": "chat-agent-terminal",
        "client_id": "client-agent-terminal",
        "sender": {"id": "agent-1", "name": "Operator"},
    }
    bot_message = {
        "id": "event-after-agent-terminal",
        "event": "BOT_MESSAGE",
        "chat_id": "chat-agent-terminal",
        "client_id": "client-agent-terminal",
        "message": {"type": "TEXT", "text": "Служебное событие"},
    }

    with build_client() as client:
        assert client.post("/webhooks/jivo/test-token", json=agent_joined).status_code == 200
        assert client.post("/webhooks/jivo/test-token", json=bot_message).status_code == 200

    with session_scope() as session:
        chat = session.query(Chat).filter(Chat.external_chat_id == "chat-agent-terminal").one()

    assert chat.status == "agent_joined"
