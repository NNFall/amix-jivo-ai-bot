from jivo.events import JivoEventType, should_stop_bot_after_event
from jivo.schemas import JivoIncomingEvent


def test_should_stop_bot_after_terminal_event() -> None:
    assert should_stop_bot_after_event(JivoEventType.CHAT_CLOSED) is True
    assert should_stop_bot_after_event(JivoEventType.AGENT_JOINED) is True
    assert should_stop_bot_after_event(JivoEventType.CLIENT_MESSAGE) is False


def test_jivo_incoming_event_schema_parses_payload() -> None:
    payload = {
        "id": "event-1",
        "event": "CLIENT_MESSAGE",
        "chat_id": "chat-1",
        "client_id": "client-1",
        "message": {"type": "TEXT", "text": "Есть артикул AB-123?"},
        "sender": {"id": "site-user", "name": "Test User"},
    }

    event = JivoIncomingEvent.model_validate(payload)

    assert event.id == "event-1"
    assert event.message is not None
    assert event.message.text == "Есть артикул AB-123?"
