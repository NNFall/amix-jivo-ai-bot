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
