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
    assert "last_product_lookup" in content


def test_assistant_service_sends_role_history_and_active_product_context(isolated_app_env) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="26139",
                article="7843 silk brash",
                normalized_article="7843SILKBRASH",
                free_stock=Decimal("1"),
                unit="шт",
                retail_price=Decimal("13493"),
                corporate_price=Decimal("10500"),
                raw_payload={},
            )
        )

    captured: dict = {}
    service = AssistantService()
    service.openai_service.enabled = True

    def fake_run_messages(**kwargs):
        messages = kwargs["messages"]
        if any(message.get("role") == "user" and message.get("content") == "скидки есть?" for message in messages):
            captured["discount_messages"] = messages
            return LLMTurnResult(
                text="По этому товару отдельной скидки в текущих данных не вижу. Могу передать менеджеру для уточнения акций.",
                tool_calls=[],
            )
        return LLMTurnResult(
            text="Проверил, 7843 silk brash сейчас в наличии 1 шт. Розничная цена 13 493 руб., корпоративная 10 500 руб.",
            tool_calls=[],
        )

    service.openai_service.run_messages = fake_run_messages

    with session_scope() as session:
        service.handle_client_message(
            session,
            external_chat_id="telegram:discount-context",
            external_client_id="telegram-user:discount-context",
            customer_name="Demo User",
            customer_text="сколько стоит 7843 silk brash",
            inbound_event_id="tg-discount-1",
            outbound_event_id="tg-discount-1:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:discount-context",
            external_client_id="telegram-user:discount-context",
            customer_name="Demo User",
            customer_text="скидки есть?",
            inbound_event_id="tg-discount-2",
            outbound_event_id="tg-discount-2:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    messages = captured["discount_messages"]
    assert reply.text.startswith("По этому товару отдельной скидки")
    assert [message["role"] for message in messages[:2]] == ["system", "system"]
    assert any(message.get("role") == "assistant" and "7843 silk brash" in message.get("content", "") for message in messages)
    assert sum(1 for message in messages if message.get("role") == "user" and message.get("content") == "скидки есть?") == 1
    non_system_content = "\n".join(
        str(message.get("content", "")) for message in messages if message.get("role") != "system"
    )
    assert "История диалога:" not in non_system_content
    assert "Последнее сообщение клиента:" not in non_system_content
    assert "active_product" in messages[1]["content"]
    assert "7843 silk brash" in messages[1]["content"]


def test_assistant_service_records_tool_flow_as_role_messages(isolated_app_env) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="1364",
                article="14.025пр.",
                normalized_article="14025ПР",
                free_stock=Decimal("7"),
                unit="шт",
                retail_price=Decimal("238"),
                raw_payload={},
            )
        )

    captured: dict = {}
    service = AssistantService()
    service.openai_service.enabled = True

    def fake_run_messages(**kwargs):
        messages = kwargs["messages"]
        if not any(message.get("role") == "tool" for message in messages):
            return LLMTurnResult(
                text=None,
                tool_calls=[
                    ToolCall(
                        name="search_products",
                        call_id="call_search_1",
                        arguments={
                            "queries": ["14.025пр."],
                            "intent": "price",
                            "use_dialog_context": False,
                        },
                    )
                ],
            )
        captured["final_messages"] = messages
        return LLMTurnResult(text="Проверил, 14.025пр. стоит 238 руб. Сейчас в наличии 7 шт.", tool_calls=[])

    service.openai_service.run_messages = fake_run_messages

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:tool-flow",
            external_client_id="telegram-user:tool-flow",
            customer_name="Demo User",
            customer_text="сколько стоит этот товар",
            inbound_event_id="tg-tool-flow",
            outbound_event_id="tg-tool-flow:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        stored_roles = [message.sender_role for message in session.query(Message).order_by(Message.id.asc()).all()]

    assert reply.text == "Проверил, 14.025пр. стоит 238 руб. Сейчас в наличии 7 шт."
    assert "assistant_tool_call" in stored_roles
    assert "tool" in stored_roles
    assert any(message.get("role") == "tool" for message in captured["final_messages"])
    assert not any(
        str(message.get("content", "")).startswith("TOOL_RESULTS_JSON")
        for message in captured["final_messages"]
    )


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

    def fail_llm_call(**kwargs):
        raise AssertionError("Company FAQ should be answered by backend rule")

    service.openai_service.run_messages = fail_llm_call

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
    assert "+7 (812) 372-66-07" in reply.text
    assert "market@amix.spb.ru" in reply.text


def test_assistant_service_answers_delivery_question_without_llm(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True

    def fail_llm_call(**kwargs):
        raise AssertionError("Delivery FAQ should be answered by backend rule")

    service.openai_service.run_messages = fail_llm_call

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:delivery-faq",
            external_client_id="telegram-user:delivery-faq",
            customer_name="Demo User",
            customer_text="Доставляете по России?",
            inbound_event_id="tg-delivery-faq",
            outbound_event_id="tg-delivery-faq:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "доставляем по России" in reply.text
    assert "точную стоимость" in reply.text.lower()


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
    assert "поможет с оформлением" not in reply.text


def test_stock_shortage_handoff_rewrites_order_wording() -> None:
    text = AssistantService._ensure_handoff_text(  # noqa: SLF001
        "Передаю вопрос менеджеру — он уточнит возможность заказа нужного количества и поможет с оформлением.",
        "requested_quantity_exceeds_stock",
    )

    assert "поможет с оформлением" not in text
    assert "уточнит возможность заказа" in text


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


def test_assistant_service_marks_short_number_as_followup_refinement() -> None:
    assert AssistantService._looks_like_price_refinement("132", ["132"])  # noqa: SLF001
    assert AssistantService._looks_like_price_refinement("цена 132", ["132"])  # noqa: SLF001
    assert AssistantService._looks_like_price_refinement("198 которая стоит", ["198"])  # noqa: SLF001


def test_assistant_service_builds_followup_refinement_context() -> None:
    context = AssistantService._build_followup_refinement_context(  # noqa: SLF001
        "цена 132",
        {
            "exact_matches": [
                {"code": "26167", "article": "МП 28ск", "retail_price": "118.00"},
                {"code": "26168", "article": "МП 28ск", "retail_price": "132.00"},
                {"code": "26169", "article": "МП 28ск", "retail_price": "198.00"},
            ]
        },
    )

    assert context["is_likely_followup_refinement"] is True
    assert context["refinement_type"] == "price"
    assert context["values"] == ["132"]
    assert context["matched_exact_count"] == 1
    assert context["matched_exact_matches"][0]["code"] == "26168"


def test_assistant_service_builds_followup_refinement_context_for_stoit_phrase() -> None:
    context = AssistantService._build_followup_refinement_context(  # noqa: SLF001
        "198 которая стоит",
        {
            "exact_matches": [
                {"code": "26167", "article": "МП 28ск", "retail_price": "118.00"},
                {"code": "26168", "article": "МП 28ск", "retail_price": "132.00"},
                {"code": "26169", "article": "МП 28ск", "retail_price": "198.00"},
            ]
        },
    )

    assert context["is_likely_followup_refinement"] is True
    assert context["refinement_type"] == "price"
    assert context["matched_exact_count"] == 1
    assert context["matched_exact_matches"][0]["code"] == "26169"


def test_assistant_service_applies_followup_refinement_to_single_match() -> None:
    lookup = {
        "status": "multiple_exact",
        "exact_matches_count": 3,
        "similar_matches_count": 0,
        "exact_matches": [
            {"code": "26167", "article": "МП 28ск", "retail_price": "118.00"},
            {"code": "26168", "article": "МП 28ск", "retail_price": "132.00"},
            {"code": "26169", "article": "МП 28ск", "retail_price": "198.00"},
        ],
        "similar_matches": [],
    }
    context = AssistantService._build_followup_refinement_context("цена 132", lookup)  # noqa: SLF001

    resolved = AssistantService._apply_followup_refinement(lookup, context)  # noqa: SLF001

    assert resolved["status"] == "exact_found"
    assert resolved["exact_matches_count"] == 1
    assert resolved["exact_matches"][0]["code"] == "26168"
    assert resolved["resolved_followup_refinement"]["value"] == "132"


def test_assistant_service_adds_code_after_price_refinement() -> None:
    text = AssistantService._ensure_refinement_code_text(  # noqa: SLF001
        "Да, нашёл МП 28ск. Сейчас в наличии 292 шт. Розничная цена 132 руб.",
        {"resolved_followup_refinement": {"code": "26168"}},
    )

    assert "Код товара 26168." in text


def test_assistant_service_sanitizes_dry_price_labels() -> None:
    text = AssistantService._sanitize_customer_reply(  # noqa: SLF001
        "Розничная цена: 13493 руб., корпоративная цена: 10500 руб."
    )

    assert "Розничная цена 13493 руб." in text.replace(",", ".")
    assert "цена:" not in text


def test_assistant_service_hides_prices_for_single_stock_only_request() -> None:
    lookup = {
        "status": "exact_found",
        "exact_matches_count": 1,
        "similar_matches_count": 0,
        "exact_matches": [
            {
                "code": "26141",
                "article": "1108035",
                "stock": "2.000",
                "retail_price": "50820.00",
                "retail_price_display": "50 820 руб.",
                "corporate_price": "24283.00",
                "corporate_price_display": "24 283 руб.",
            }
        ],
        "similar_matches": [],
    }

    filtered = AssistantService._apply_stock_only_policy(lookup, True)  # noqa: SLF001

    match = filtered["exact_matches"][0]
    assert match["retail_price"] is None
    assert match["retail_price_display"] is None
    assert match["corporate_price"] is None
    assert match["corporate_price_display"] is None


def test_assistant_service_writes_llm_debug_payload(isolated_app_env, monkeypatch, tmp_path) -> None:
    log_path = tmp_path / "llm_debug.jsonl"
    monkeypatch.setenv("ASSISTANT_DEBUG_LLM_PAYLOADS", "true")
    monkeypatch.setenv("ASSISTANT_DEBUG_LLM_PAYLOADS_PATH", str(log_path))
    get_settings.cache_clear()
    service = AssistantService()

    service._log_llm_debug_event(  # noqa: SLF001
        "test_request",
        {
            "messages": [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "Клиент: привет"},
            ]
        },
    )

    content = log_path.read_text(encoding="utf-8")
    assert '"stage": "test_request"' in content
    assert '"role": "system"' in content
    assert '"role": "user"' in content
