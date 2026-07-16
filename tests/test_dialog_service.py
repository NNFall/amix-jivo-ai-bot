from core.dialog_service import DialogService
from database.db import session_scope
from database.repositories import append_message, get_or_create_chat, get_or_create_customer


def test_transcript_skips_tool_messages(isolated_app_env) -> None:
    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="customer:1")
        get_or_create_chat(session, "chat:1", customer.id)
        append_message(session, external_chat_id="chat:1", sender_role="client", text="есть мп 28ск")
        append_message(
            session,
            external_chat_id="chat:1",
            sender_role="assistant_tool_call",
            text="",
            payload={"tool_calls": [{"id": "call_1"}]},
        )
        append_message(
            session,
            external_chat_id="chat:1",
            sender_role="tool",
            text='{"query":"МП28СКINTENTPRODUCTINFO","exact_matches_count":3}',
            payload={"tool_name": "search_products"},
        )
        append_message(session, external_chat_id="chat:1", sender_role="bot", text="Уточните код или цену.")

        transcript = DialogService().get_transcript(session, "chat:1")

    assert "Клиент: есть мп 28ск" in transcript
    assert "Бот: Уточните код или цену." in transcript
    assert "МП28СКINTENTPRODUCTINFO" not in transcript
    assert "exact_matches_count" not in transcript


def test_get_llm_messages_returns_complete_chronological_history(isolated_app_env) -> None:
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "search_products", "arguments": '{"query":"MP-01"}'},
        }
    ]
    expected = [
        {"role": "user", "content": "message 00"},
        {"role": "assistant", "content": "", "tool_calls": tool_calls},
        {
            "role": "tool",
            "content": '{"article":"MP-01","stock":"12"}',
            "tool_call_id": "call_1",
            "name": "search_products",
        },
    ]

    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="customer:full-history")
        get_or_create_chat(session, "chat:full-history", customer.id)
        append_message(session, "chat:full-history", "client", "message 00")
        append_message(
            session,
            "chat:full-history",
            "assistant_tool_call",
            "",
            payload={"tool_calls": tool_calls},
        )
        append_message(
            session,
            "chat:full-history",
            "tool",
            '{"article":"MP-01","stock":"12"}',
            payload={"tool_call_id": "call_1", "tool_name": "search_products"},
        )

        for index in range(1, 21):
            sender_role = "client" if index % 2 else "bot"
            llm_role = "user" if sender_role == "client" else "assistant"
            content = f"message {index:02d}"
            append_message(session, "chat:full-history", sender_role, content)
            expected.append({"role": llm_role, "content": content})

        messages = DialogService(history_limit=3).get_llm_messages(session, "chat:full-history")

    assert messages == expected
