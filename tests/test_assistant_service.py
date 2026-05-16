from decimal import Decimal

from core.assistant_service import (
    ARTICLE_REQUIRED_TEXT,
    AssistantService,
    SAFE_FALLBACK_TEXT,
    TELEGRAM_DEMO_HANDOFF_TEXT,
)
from database.db import session_scope
from database.models import Handoff, Message, Product
from llm.openai_client import LLMTurnResult, ToolCall


def test_assistant_service_returns_product_reply(isolated_app_env) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="1",
                article="AB-123",
                normalized_article="AB123",
                free_stock=Decimal("4"),
                unit="шт.",
                retail_price=Decimal("120"),
                corporate_price=Decimal("100"),
                raw_payload={},
            )
        )

    service = AssistantService()
    service.openai_service.enabled = False
    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:1",
            external_client_id="telegram-user:1",
            customer_name="Demo User",
            customer_text="Есть AB-123?",
            inbound_event_id="tg-1",
            outbound_event_id="tg-1:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "Артикул AB-123 найден." in reply.text
    assert reply.handoff_reason is None

    with session_scope() as session:
        messages = session.query(Message).order_by(Message.id.asc()).all()

    assert len(messages) == 2
    assert messages[0].external_event_id == "tg-1"
    assert messages[1].external_event_id == "tg-1:bot"


def test_assistant_service_returns_demo_handoff_reply(isolated_app_env) -> None:
    with session_scope() as session:
        reply = AssistantService().handle_client_message(
            session,
            external_chat_id="telegram:2",
            external_client_id="telegram-user:2",
            customer_name="Demo User",
            customer_text="Нужен менеджер для подбора аналога",
            inbound_event_id="tg-2",
            outbound_event_id="tg-2:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert reply.text == TELEGRAM_DEMO_HANDOFF_TEXT
    assert reply.handoff_reason == "client_requested_manager"

    with session_scope() as session:
        handoffs = session.query(Handoff).all()

    assert len(handoffs) == 1


def test_assistant_service_uses_safe_fallback_without_openai(isolated_app_env) -> None:
    with session_scope() as session:
        reply = AssistantService().handle_client_message(
            session,
            external_chat_id="telegram:3",
            external_client_id="telegram-user:3",
            customer_name="Demo User",
            customer_text="Здравствуйте, подскажите пожалуйста",
            inbound_event_id="tg-3",
            outbound_event_id="tg-3:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert reply.text == SAFE_FALLBACK_TEXT


def test_assistant_service_requests_article_for_stock_question(isolated_app_env) -> None:
    with session_scope() as session:
        reply = AssistantService().handle_client_message(
            session,
            external_chat_id="telegram:4",
            external_client_id="telegram-user:4",
            customer_name="Demo User",
            customer_text="Подскажите цену и наличие",
            inbound_event_id="tg-4",
            outbound_event_id="tg-4:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert reply.text == ARTICLE_REQUIRED_TEXT
    assert reply.handoff_reason is None


def test_assistant_service_reports_missing_article_when_not_found(isolated_app_env) -> None:
    with session_scope() as session:
        reply = AssistantService().handle_client_message(
            session,
            external_chat_id="telegram:5",
            external_client_id="telegram-user:5",
            customer_name="Demo User",
            customer_text="Есть артикул ZZ-999?",
            inbound_event_id="tg-5",
            outbound_event_id="tg-5:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "ZZ999" in reply.text


def test_assistant_service_finds_product_from_split_prefix_query(isolated_app_env) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="77",
                article="MP28CK",
                normalized_article="MP28CK",
                free_stock=Decimal("2"),
                unit="шт.",
                retail_price=Decimal("500"),
                corporate_price=Decimal("450"),
                raw_payload={},
            )
        )

    with session_scope() as session:
        reply = AssistantService().handle_client_message(
            session,
            external_chat_id="telegram:6",
            external_client_id="telegram-user:6",
            customer_name="Demo User",
            customer_text="МП 28ск",
            inbound_event_id="tg-6",
            outbound_event_id="tg-6:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "MP28CK" in reply.text


def test_assistant_service_uses_direct_response_without_lookup(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text="Добрый день! Чем могу помочь?",
        tool_calls=[],
    )

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:7",
            external_client_id="telegram-user:7",
            customer_name="Demo User",
            customer_text="добрый день",
            inbound_event_id="tg-7",
            outbound_event_id="tg-7:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert reply.text == "Добрый день! Чем могу помочь?"


def test_assistant_service_uses_backend_prelookup_for_article_query(isolated_app_env) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="7843-BR",
                article="7843 silk brash",
                normalized_article="7843SILKBRASH",
                free_stock=Decimal("5"),
                unit="шт.",
                retail_price=Decimal("1000"),
                corporate_price=Decimal("900"),
                raw_payload={},
            )
        )

    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text="По базе нашел варианты и цену.",
        tool_calls=[],
    )

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:8",
            external_client_id="telegram-user:8",
            customer_name="Demo User",
            customer_text="я хочу цену примерную узнать у 7843 silk brash",
            inbound_event_id="tg-8",
            outbound_event_id="tg-8:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert reply.handoff_reason is None
    assert reply.text == "По базе нашел варианты и цену."


def test_assistant_service_handles_tool_based_handoff(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text=None,
        tool_calls=[ToolCall(name="handoff_to_manager", arguments={"reason": "complex_technical_question"})],
    )

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:9",
            external_client_id="telegram-user:9",
            customer_name="Demo User",
            customer_text="подберите аналог",
            inbound_event_id="tg-9",
            outbound_event_id="tg-9:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert reply.handoff_reason == "complex_technical_question"
    assert reply.text == TELEGRAM_DEMO_HANDOFF_TEXT
