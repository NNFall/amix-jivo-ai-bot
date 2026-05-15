from decimal import Decimal

from core.assistant_service import AssistantService, SAFE_FALLBACK_TEXT, TELEGRAM_DEMO_HANDOFF_TEXT
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
