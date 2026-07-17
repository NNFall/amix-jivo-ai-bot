import json

from core.dialog_service import DialogService
from database.db import session_scope
from database.repositories import append_message, get_or_create_chat, get_or_create_customer


def test_visible_transcript_skips_internal_tool_messages(isolated_app_env) -> None:
    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="customer:transcript")
        get_or_create_chat(session, "chat:transcript", customer.id)
        append_message(session, "chat:transcript", "client", "Проверьте товар")
        append_message(
            session,
            "chat:transcript",
            "assistant_tool_call",
            "",
            payload={"tool_calls": [{"id": "call-1"}]},
        )
        append_message(
            session,
            "chat:transcript",
            "tool",
            '{"status":"ok"}',
            payload={"tool_name": "search_products"},
        )
        append_message(session, "chat:transcript", "bot", "Товар найден.")

        transcript = DialogService().get_transcript(session, "chat:transcript")

    assert transcript == "Клиент: Проверьте товар\nБот: Товар найден."


def test_llm_history_is_complete_chronological_and_unmodified(isolated_app_env) -> None:
    tool_calls = [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "search_products", "arguments": '{"queries":[{"query":"770"}]}'},
        }
    ]
    tool_result = {
        "tool_name": "search_products",
        "status": "ok",
        "result": {"stock": "220", "retail_price": "473.00"},
    }

    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="customer:history")
        get_or_create_chat(session, "chat:history", customer.id)
        append_message(session, "chat:history", "client", "Первое сообщение")
        append_message(session, "chat:history", "bot", "Первый ответ")
        append_message(session, "chat:history", "client", "Проверьте 770")
        append_message(
            session,
            "chat:history",
            "assistant_tool_call",
            "",
            payload={"content": "", "tool_calls": tool_calls},
        )
        append_message(
            session,
            "chat:history",
            "tool",
            json.dumps(tool_result, ensure_ascii=False),
            payload={
                "tool_name": "search_products",
                "tool_call_id": "call-1",
                "content": json.dumps(tool_result, ensure_ascii=False),
            },
        )
        append_message(session, "chat:history", "bot", "Нужное количество доступно.")
        append_message(session, "chat:history", "client", "Тогда продолжим")

        messages = DialogService().get_llm_messages(session, "chat:history")

    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
    ]
    assert messages[3]["tool_calls"] == tool_calls
    assert json.loads(messages[4]["content"]) == tool_result
    assert "220" in messages[4]["content"]
    assert messages[-1]["content"] == "Тогда продолжим"


def test_llm_history_has_no_message_limit(isolated_app_env) -> None:
    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="customer:long-history")
        get_or_create_chat(session, "chat:long-history", customer.id)
        for index in range(60):
            role = "client" if index % 2 == 0 else "bot"
            append_message(session, "chat:long-history", role, f"message {index:02d}")

        messages = DialogService().get_llm_messages(session, "chat:long-history")

    assert len(messages) == 60
    assert messages[0]["content"] == "message 00"
    assert messages[-1]["content"] == "message 59"
