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
from settings import get_settings


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

    assert "Да, нашёл AB-123." in reply.text
    assert "Сейчас в наличии 4 шт." in reply.text
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

    assert "ZZ-999" in reply.text


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
    assert "**" not in reply.text


def test_assistant_service_hides_similar_aliases_when_exact_found(isolated_app_env) -> None:
    with session_scope() as session:
        session.add_all(
            [
                Product(
                    code="22608",
                    article="P-AM02/B-S",
                    normalized_article="PAM02BS",
                    free_stock=Decimal("1"),
                    unit="шт",
                    raw_payload={},
                ),
                Product(
                    code="22609",
                    article="P-AM02/GR-S",
                    normalized_article="PAM02GRS",
                    free_stock=Decimal("2"),
                    unit="шт",
                    raw_payload={},
                ),
            ]
        )

    service = AssistantService()
    service.openai_service.enabled = False
    with session_scope() as session:
        lookup = service._search_products_by_queries(  # noqa: SLF001
            session,
            queries=["PAM02BS", "AM02"],
            reason="stock",
        )

    assert lookup["exact_matches_count"] == 1
    assert lookup["similar_matches_count"] == 0
    assert all(item["status"] != "similar_found" for item in lookup["per_query_results"])


def test_assistant_service_uses_direct_response_without_lookup(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text="**Добрый день!**\n- Чем могу помочь?",
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

    assert reply.text == "Добрый день!\nЧем могу помочь?"


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
    assert "Для точного подбора нужны параметры" in reply.text
    assert "подключится к диалогу" in reply.text


def test_assistant_service_passes_backend_actions_to_facts_prompt(isolated_app_env) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="770",
                article="14.023пр.",
                normalized_article="14023ПР",
                free_stock=Decimal("220"),
                unit="шт",
                retail_price=Decimal("473"),
                raw_payload={},
            )
        )

    captured: dict = {}
    service = AssistantService()
    service.openai_service.enabled = True

    def capture_messages(**kwargs):
        captured["messages"] = kwargs["messages"]
        return LLMTurnResult(text="Артикул найден. Передаю вопрос менеджеру.", tool_calls=[])

    service.openai_service.run_messages = capture_messages

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:backend-actions",
            external_client_id="telegram-user:backend-actions",
            customer_name="Demo User",
            customer_text="Хочу заказать 10 штук 14.023пр.",
            inbound_event_id="tg-backend-actions",
            outbound_event_id="tg-backend-actions:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    content = captured["messages"][1]["content"]
    assert reply.handoff_reason == "order_request"
    assert "backend_actions" in content
    assert "handoff_to_manager_called" in content
    assert "order_request" in content
    assert "results" in content


def test_assistant_service_forces_backend_handoff_for_complex_question(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True

    def fail_llm_call(**kwargs):
        raise AssertionError("LLM should not handle complex handoff-only questions")

    service.openai_service.run_messages = fail_llm_call

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:10",
            external_client_id="telegram-user:10",
            customer_name="Demo User",
            customer_text="подберите аналог для петли",
            inbound_event_id="tg-10",
            outbound_event_id="tg-10:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert reply.handoff_reason == "complex_technical_question"
    assert "Для точного подбора нужны параметры" in reply.text
    assert "подключится к диалогу" in reply.text


def test_assistant_service_allows_company_contact_question_without_handoff(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text="Магазин находится в Санкт-Петербурге, ул. Якорная, 15, лит. Б.",
        tool_calls=[],
    )

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:11",
            external_client_id="telegram-user:11",
            customer_name="Demo User",
            customer_text="где вы находитесь и какой телефон?",
            inbound_event_id="tg-11",
            outbound_event_id="tg-11:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert reply.handoff_reason is None
    assert "Якорная" in reply.text


def test_assistant_service_mentions_code_for_code_lookup(isolated_app_env) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="1364",
                article="14.025пр.",
                normalized_article="14025ПР",
                free_stock=Decimal("7"),
                unit="шт",
                retail_price=Decimal("238"),
                corporate_price=Decimal("165.98"),
                raw_payload={},
            )
        )

    service = AssistantService()
    service.openai_service.enabled = False
    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:code-lookup",
            external_client_id="telegram-user:code-lookup",
            customer_name="Demo User",
            customer_text="Проверьте код 1364",
            inbound_event_id="tg-code-lookup",
            outbound_event_id="tg-code-lookup:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "По коду 1364 нашёл артикул 14.025пр." in reply.text


def test_assistant_service_uses_raw_query_for_similar_reply(isolated_app_env) -> None:
    with session_scope() as session:
        session.add_all(
            [
                Product(
                    code="769",
                    article="14.023л.",
                    normalized_article="14023Л",
                    free_stock=Decimal("253"),
                    unit="шт",
                    retail_price=Decimal("473"),
                    raw_payload={},
                ),
                Product(
                    code="770",
                    article="14.023пр.",
                    normalized_article="14023ПР",
                    free_stock=Decimal("220"),
                    unit="шт",
                    retail_price=Decimal("473"),
                    raw_payload={},
                ),
            ]
        )

    service = AssistantService()
    service.openai_service.enabled = False
    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:raw-query",
            external_client_id="telegram-user:raw-query",
            customer_name="Demo User",
            customer_text="14.023",
            inbound_event_id="tg-raw-query",
            outbound_event_id="tg-raw-query:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "Точного совпадения по 14.023" in reply.text
    assert "по 14023" not in reply.text


def test_assistant_service_does_not_match_code_from_punctuated_article_query(isolated_app_env) -> None:
    with session_scope() as session:
        session.add_all(
            [
                Product(
                    code="14023",
                    article="05.088.256 MC/AMIX",
                    normalized_article="05088256MCAMIX",
                    free_stock=Decimal("149"),
                    unit="шт",
                    retail_price=Decimal("181"),
                    raw_payload={},
                ),
                Product(
                    code="770",
                    article="14.023пр.",
                    normalized_article="14023ПР",
                    free_stock=Decimal("220"),
                    unit="шт",
                    retail_price=Decimal("473"),
                    raw_payload={},
                ),
            ]
        )

    service = AssistantService()
    service.openai_service.enabled = False
    with session_scope() as session:
        lookup = service._search_products_by_queries(  # noqa: SLF001
            session,
            queries=["14023"],
            reason="product_info",
            customer_text="14.023",
        )

    assert lookup["status"] == "similar_found"
    assert all(item.get("code") != "14023" for item in lookup["exact_matches"])
    assert lookup["per_query_results"][0]["query"] == "14.023"
    assert lookup["per_query_results"][0]["raw_backend_query"] == "14023"


def test_assistant_service_prioritizes_stock_shortage_over_order_handoff(isolated_app_env) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="22608",
                article="P-AM02/B-S",
                normalized_article="PAM02BS",
                free_stock=Decimal("1"),
                unit="шт",
                raw_payload={},
            )
        )

    service = AssistantService()
    service.openai_service.enabled = False
    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:stock-shortage",
            external_client_id="telegram-user:stock-shortage",
            customer_name="Demo User",
            customer_text="Хочу заказать 5 штук P-AM02/B-S",
            inbound_event_id="tg-stock-shortage",
            outbound_event_id="tg-stock-shortage:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert reply.handoff_reason == "requested_quantity_exceeds_stock"
    assert "Сейчас в наличии 1 шт." in reply.text
    assert "уточнит возможность заказа или замены" in reply.text
    assert "поможет оформить" not in reply.text


def test_assistant_service_can_hide_corporate_price(isolated_app_env, monkeypatch) -> None:
    monkeypatch.setenv("SHOW_CORPORATE_PRICE", "false")
    get_settings.cache_clear()
    with session_scope() as session:
        session.add(
            Product(
                code="1364",
                article="14.025пр.",
                normalized_article="14025ПР",
                free_stock=Decimal("7"),
                unit="шт",
                retail_price=Decimal("238"),
                corporate_price=Decimal("165.98"),
                raw_payload={},
            )
        )

    service = AssistantService()
    service.openai_service.enabled = False
    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:hide-corporate",
            external_client_id="telegram-user:hide-corporate",
            customer_name="Demo User",
            customer_text="Сколько стоит 14.025пр.?",
            inbound_event_id="tg-hide-corporate",
            outbound_event_id="tg-hide-corporate:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "Розничная цена 238 руб." in reply.text
    assert "Корпоративная" not in reply.text
