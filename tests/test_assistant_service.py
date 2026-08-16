from decimal import Decimal

from core.assistant_service import (
    HANDOFF_ALREADY_REQUESTED_TEXT,
    PROVIDER_DELAY_TEXT,
    AssistantService,
)
from database.db import session_scope
from database.models import Chat, Handoff, LLMCall, Message, Product
from llm.openai_client import LLMTurnResult, ToolCall
from products.article_utils import normalize_article


def test_disabled_llm_returns_safe_service_message(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = False

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:llm-disabled",
            external_client_id="telegram-user:llm-disabled",
            customer_name="Клиент",
            customer_text="Есть вопрос",
            inbound_event_id="llm-disabled-in",
            outbound_event_id="llm-disabled-out",
            payload={},
            handoff_mode="demo",
        )
        messages = session.query(Message).order_by(Message.id.asc()).all()

    assert reply.text == PROVIDER_DELAY_TEXT
    assert [message.sender_role for message in messages] == ["client", "bot"]


def test_two_pending_user_messages_are_sent_as_two_history_items(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    requests: list[dict] = []
    service.openai_service.run_messages = lambda **kwargs: (
        requests.append(kwargs) or LLMTurnResult(text="Ответ по обоим сообщениям.", tool_calls=[])
    )

    with session_scope() as session:
        service.record_client_message(
            session,
            external_chat_id="telegram:pending-two",
            external_client_id="telegram-user:pending-two",
            customer_name="Клиент",
            customer_text="Первый вопрос",
            inbound_event_id="pending-two-1",
        )
        service.record_client_message(
            session,
            external_chat_id="telegram:pending-two",
            external_client_id="telegram-user:pending-two",
            customer_name="Клиент",
            customer_text="Дополнение к нему",
            inbound_event_id="pending-two-2",
        )
        reply = service.handle_pending_client_messages(
            session,
            external_chat_id="telegram:pending-two",
            outbound_event_id="pending-two-out",
            handoff_mode="demo",
        )

    visible = [message for message in requests[0]["messages"] if message["role"] != "system"]
    assert visible == [
        {"role": "user", "content": "Первый вопрос"},
        {"role": "user", "content": "Дополнение к нему"},
    ]
    assert reply.text == "Ответ по обоим сообщениям."


def test_stale_turn_discards_reply_but_keeps_usage(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text="Устаревший ответ",
        tool_calls=[],
        usage={"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 120},
        latency_ms=50,
    )
    checks = iter([True, True, False])

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:stale",
            external_client_id="telegram-user:stale",
            customer_name="Клиент",
            customer_text="Первое сообщение",
            inbound_event_id="stale-in",
            outbound_event_id="stale-out",
            payload={},
            handoff_mode="demo",
            is_turn_current=lambda: next(checks),
        )

    assert reply.superseded is True
    with session_scope() as session:
        assert session.query(LLMCall).count() == 1
        assert session.query(Message).filter(Message.sender_role == "bot").count() == 0


def test_antigravity_usage_is_persisted_with_model_and_thinking_tokens(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.provider = "antigravity"
    service.openai_service.antigravity_model = "gemini-3.7-flash-low"
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text="Проверил, товар есть в наличии.",
        tool_calls=[],
        usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 130},
        latency_ms=2400,
    )

    with session_scope() as session:
        service.handle_client_message(
            session,
            external_chat_id="telegram:antigravity-usage",
            external_client_id="telegram-user:antigravity-usage",
            customer_name="Клиент",
            customer_text="Проверьте товар",
            inbound_event_id="antigravity-usage-in",
            outbound_event_id="antigravity-usage-out",
            payload={},
            handoff_mode="demo",
        )

    with session_scope() as session:
        call = session.query(LLMCall).one()
        assert call.provider == "antigravity"
        assert call.model == "gemini-3.7-flash-low"
        assert call.prompt_tokens == 100
        assert call.completion_tokens == 20
        assert call.thinking_tokens == 10
        assert call.total_tokens == 130
        assert call.latency_ms == 2400


def test_stale_turn_rolls_back_tool_messages_and_handoff_side_effects(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text=None,
        tool_calls=[
            ToolCall(
                name="handoff_to_manager",
                arguments={
                    "reason": "client_requested_manager",
                    "summary": "Клиент попросил менеджера.",
                    "customer_message": "Передаю вопрос менеджеру.",
                },
                call_id="stale-handoff",
            )
        ],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    current = {"value": True}
    original_register = service.handoff_service.register_handoff

    def stale_during_handoff(session, external_chat_id: str, reason: str) -> None:
        original_register(session, external_chat_id, reason)
        current["value"] = False

    service.handoff_service.register_handoff = stale_during_handoff

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:stale-tool",
            external_client_id="telegram-user:stale-tool",
            customer_name="Клиент",
            customer_text="Позовите менеджера",
            inbound_event_id="stale-tool-in",
            outbound_event_id="stale-tool-out",
            payload={},
            handoff_mode="demo",
            is_turn_current=lambda: current["value"],
        )

    assert reply.superseded is True
    with session_scope() as session:
        assert [message.sender_role for message in session.query(Message).all()] == ["client"]
        assert session.query(Handoff).count() == 0
        assert session.query(LLMCall).count() == 1


def test_jivo_handoff_is_not_completed_before_external_invite(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text=None,
        tool_calls=[
            ToolCall(
                name="handoff_to_manager",
                arguments={
                    "reason": "client_requested_manager",
                    "summary": "Клиент попросил менеджера.",
                    "customer_message": "Передаю вопрос менеджеру.",
                },
                call_id="jivo-pending-handoff",
            )
        ],
    )

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="jivo:pending-handoff",
            external_client_id="jivo-user:pending-handoff",
            customer_name="Клиент",
            customer_text="Позовите менеджера",
            inbound_event_id="jivo-pending-in",
            outbound_event_id="jivo-pending-out",
            payload={},
            handoff_mode="jivo",
        )
        chat_status = session.query(Message).filter(Message.sender_role == "bot").one().payload["source"]

    assert reply.handoff_reason == "client_requested_manager"
    assert chat_status == "llm_handoff"
    with session_scope() as session:
        assert session.query(Handoff).count() == 0
        assert session.query(Chat).one().status == "active"


def test_handoff_tool_persists_action_and_blocks_later_bot_turn(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text=None,
        tool_calls=[
            ToolCall(
                name="handoff_to_manager",
                arguments={
                    "reason": "client_requested_manager",
                    "summary": "Клиент попросил менеджера.",
                    "customer_message": "Передаю вопрос менеджеру. Он подключится к диалогу.",
                },
                call_id="handoff-client-request",
            )
        ],
    )

    with session_scope() as session:
        first = service.handle_client_message(
            session,
            external_chat_id="telegram:handoff",
            external_client_id="telegram-user:handoff",
            customer_name="Клиент",
            customer_text="Хочу поговорить с человеком",
            inbound_event_id="handoff-in-1",
            outbound_event_id="handoff-out-1",
            payload={},
            handoff_mode="demo",
        )
        second = service.handle_client_message(
            session,
            external_chat_id="telegram:handoff",
            external_client_id="telegram-user:handoff",
            customer_name="Клиент",
            customer_text="Ещё вопрос",
            inbound_event_id="handoff-in-2",
            outbound_event_id="handoff-out-2",
            payload={},
            handoff_mode="demo",
        )
        handoffs = session.query(Handoff).all()

    assert first.handoff_reason == "client_requested_manager"
    assert second.text == HANDOFF_ALREADY_REQUESTED_TEXT
    assert len(handoffs) == 1


def test_search_tool_preserves_query_order_and_each_quantity(isolated_app_env) -> None:
    with session_scope() as session:
        session.add_all(
            [
                Product(
                    code="770",
                    article="14.023пр.",
                    normalized_article=normalize_article("14.023пр."),
                    free_stock=Decimal("5"),
                    unit="шт",
                    raw_payload={},
                ),
                Product(
                    code="28834",
                    article="МП ЦК белая",
                    normalized_article=normalize_article("МП ЦК белая"),
                    free_stock=Decimal("2"),
                    unit="шт",
                    raw_payload={},
                ),
            ]
        )

    service = AssistantService()
    with session_scope() as session:
        result = service._execute_search_products(  # noqa: SLF001
            session,
            {
                "queries": [
                    {"query": "28834", "requested_quantity": 3},
                    {"query": "770", "requested_quantity": 2},
                ]
            },
        )

    assert result["result"]["query_order"] == ["28834", "770"]
    first, second = result["result"]["results"]
    assert first["requested_quantity"] == 3
    assert first["requested_quantity_available"] is False
    assert second["requested_quantity"] == 2
    assert second["requested_quantity_available"] is True


def test_unknown_provider_tool_is_returned_as_tool_error_then_model_continues(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    requests: list[dict] = []

    def fake_model(**kwargs):
        requests.append(kwargs)
        if len(requests) == 1:
            return LLMTurnResult(
                text=None,
                tool_calls=[ToolCall(name="unknown_tool", arguments={}, call_id="unknown-call")],
            )
        return LLMTurnResult(text="Не смог выполнить это действие.", tool_calls=[])

    service.openai_service.run_messages = fake_model
    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:unknown-tool",
            external_client_id="telegram-user:unknown-tool",
            customer_name="Клиент",
            customer_text="Вопрос",
            inbound_event_id="unknown-tool-in",
            outbound_event_id="unknown-tool-out",
            payload={},
            handoff_mode="demo",
        )

    assert reply.text == "Не смог выполнить это действие."
    assert len(requests) == 2
    tool_message = next(message for message in requests[1]["messages"] if message["role"] == "tool")
    assert "unsupported_tool" in tool_message["content"]


def test_record_client_message_is_idempotent_for_same_external_event(isolated_app_env) -> None:
    service = AssistantService()
    with session_scope() as session:
        for _ in range(2):
            service.record_client_message(
                session,
                external_chat_id="chat-idempotent",
                external_client_id="client-idempotent",
                customer_name=None,
                customer_text="Одно сообщение",
                inbound_event_id="event-idempotent",
            )

    with session_scope() as session:
        messages = session.query(Message).all()
        assert len(messages) == 1
        assert messages[0].external_event_id == "event-idempotent"


def test_stale_second_model_round_removes_committed_tool_branch_but_keeps_usage(
    isolated_app_env,
) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    current = {"value": True}
    calls = 0

    def fake_model(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return LLMTurnResult(
                text=None,
                tool_calls=[
                    ToolCall(
                        name="search_products",
                        arguments={"queries": [{"query": "missing"}]},
                        call_id="search-stale",
                    )
                ],
                usage={"total_tokens": 10},
            )
        current["value"] = False
        return LLMTurnResult(text="Late reply", tool_calls=[], usage={"total_tokens": 20})

    service.openai_service.run_messages = fake_model
    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="chat-stale-second-round",
            external_client_id="client-stale-second-round",
            customer_name=None,
            customer_text="Проверьте товар",
            inbound_event_id="stale-second-round-in",
            outbound_event_id="stale-second-round-out",
            handoff_mode="jivo",
            is_turn_current=lambda: current["value"],
        )

    assert reply.superseded is True
    with session_scope() as session:
        assert [message.sender_role for message in session.query(Message).all()] == ["client"]
        assert session.query(LLMCall).count() == 2
