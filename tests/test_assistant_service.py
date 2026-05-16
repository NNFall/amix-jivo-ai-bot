from decimal import Decimal

from core.assistant_service import (
    ARTICLE_REQUIRED_TEXT,
    AssistantService,
    SAFE_FALLBACK_TEXT,
    TELEGRAM_DEMO_HANDOFF_TEXT,
)
from database.db import session_scope
from database.models import Handoff, Message, Product


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

    with session_scope() as session:
        reply = AssistantService().handle_client_message(
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

    assert "Не нашёл артикул ZZ999" in reply.text
    assert "Проверьте написание артикула." in reply.text


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
