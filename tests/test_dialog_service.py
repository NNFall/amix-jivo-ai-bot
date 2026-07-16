import json

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


def test_transcript_returns_complete_visible_history_without_limit_state(isolated_app_env) -> None:
    expected_lines = []

    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="customer:full-transcript")
        get_or_create_chat(session, "chat:full-transcript", customer.id)

        for index in range(22):
            sender_role = "client" if index % 2 == 0 else "bot"
            speaker = "Клиент" if sender_role == "client" else "Бот"
            text = f"visible message {index:02d}"
            append_message(session, "chat:full-transcript", sender_role, text)
            expected_lines.append(f"{speaker}: {text}")

            if index == 10:
                append_message(
                    session,
                    "chat:full-transcript",
                    "assistant_tool_call",
                    "",
                    payload={"tool_calls": [{"id": "hidden_call"}]},
                )
                append_message(
                    session,
                    "chat:full-transcript",
                    "tool",
                    '{"hidden_tool_payload":true}',
                    payload={"tool_name": "search_products"},
                )

        service = DialogService()
        transcript = service.get_transcript(session, "chat:full-transcript")

    assert transcript.splitlines() == expected_lines
    assert "hidden_call" not in transcript
    assert "hidden_tool_payload" not in transcript
    assert not hasattr(service, "history_limit")


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
            "content": '{"article": "MP-01"}',
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

        messages = DialogService().get_llm_messages(session, "chat:full-history")

    assert messages == expected


def test_get_llm_messages_hides_exact_stock_from_legacy_search_results(isolated_app_env) -> None:
    tool_result = {
        "tool_name": "search_products",
        "status": "ok",
        "result": {
            "товары": [
                {
                    "код_товара": "770",
                    "артикул": "14.023пр.",
                    "остаток": "220 шт",
                    "stock": "220",
                    "requested_quantity_available": True,
                }
            ]
        },
    }

    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="customer:legacy-stock")
        get_or_create_chat(session, "chat:legacy-stock", customer.id)
        append_message(session, "chat:legacy-stock", "client", "Нужно 2 штуки 14.023пр.")
        append_message(
            session,
            "chat:legacy-stock",
            "assistant_tool_call",
            "",
            payload={
                "tool_calls": [
                    {
                        "id": "legacy-stock-call",
                        "type": "function",
                        "function": {"name": "search_products", "arguments": "{}"},
                    }
                ]
            },
        )
        append_message(
            session,
            "chat:legacy-stock",
            "tool",
            json.dumps(tool_result, ensure_ascii=False),
            payload={"tool_call_id": "legacy-stock-call", "tool_name": "search_products"},
        )

        messages = DialogService().get_llm_messages(session, "chat:legacy-stock")

    visible_result = json.loads(messages[2]["content"])
    serialized = json.dumps(visible_result, ensure_ascii=False).lower()
    assert "220" not in serialized
    assert "остаток" not in serialized
    assert visible_result["result"]["товары"][0]["requested_quantity_available"] is True


def test_dialog_service_redacts_exact_stock_from_legacy_bot_reply(isolated_app_env) -> None:
    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="customer:legacy-bot-stock")
        get_or_create_chat(session, "chat:legacy-bot-stock", customer.id)
        append_message(session, "chat:legacy-bot-stock", "client", "Сколько осталось 14.023пр.?")
        append_message(session, "chat:legacy-bot-stock", "bot", "Сейчас в наличии ровно 220 шт.")

        messages = DialogService().get_llm_messages(session, "chat:legacy-bot-stock")

    serialized = json.dumps(messages, ensure_ascii=False)
    assert "220" not in serialized
    assert "точный остаток скрыт" in serialized.lower()


def test_dialog_service_redacts_legacy_stock_without_unit(isolated_app_env) -> None:
    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="customer:legacy-bare-stock")
        get_or_create_chat(session, "chat:legacy-bare-stock", customer.id)
        append_message(session, "chat:legacy-bare-stock", "client", "Какой остаток?")
        append_message(session, "chat:legacy-bare-stock", "bot", "Остаток: 220.")

        messages = DialogService().get_llm_messages(session, "chat:legacy-bare-stock")

    serialized = json.dumps(messages, ensure_ascii=False)
    assert "220" not in serialized
    assert "точный остаток скрыт" in serialized.lower()
