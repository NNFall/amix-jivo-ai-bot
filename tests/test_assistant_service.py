from decimal import Decimal

from core.assistant_service import (
    ARTICLE_REQUIRED_TEXT,
    AssistantService,
    HANDOFF_ALREADY_REQUESTED_TEXT,
    SAFE_FALLBACK_TEXT,
    TELEGRAM_DEMO_HANDOFF_TEXT,
)
from database.db import session_scope
from database.models import Handoff, Message, Product
from llm.openai_client import LLMTurnResult, ToolCall
from products.article_utils import normalize_article
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

    assert len(messages) == 4
    assert messages[0].external_event_id == "tg-1"
    assert [message.sender_role for message in messages] == ["client", "assistant_tool_call", "tool", "bot"]
    assert messages[1].payload["source"] == "backend_prelookup_tool_call"
    assert messages[2].payload["source"] == "backend_prelookup_tool_result"
    assert messages[3].external_event_id == "tg-1:bot"


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
        messages = session.query(Message).order_by(Message.id.asc()).all()

    assert len(handoffs) == 1
    assert [message.sender_role for message in messages] == ["client", "assistant_tool_call", "tool", "bot"]
    assert messages[1].payload["tool_calls"][0]["function"]["name"] == "handoff_to_manager"
    assert messages[2].payload["tool_name"] == "handoff_to_manager"
    assert '"real_jivo_invite_sent": false' in messages[2].payload["content"]
    assert messages[3].payload["backend_actions"]["handoff_to_manager_called"] is True
    assert messages[3].payload["backend_actions"]["real_jivo_invite_sent"] is False


def test_assistant_service_blocks_normal_reply_after_handoff(isolated_app_env) -> None:
    service = AssistantService()

    with session_scope() as session:
        first_reply = service.handle_client_message(
            session,
            external_chat_id="telegram:handoff-block",
            external_client_id="telegram-user:handoff-block",
            customer_name="Demo User",
            customer_text="Нужен менеджер",
            inbound_event_id="tg-handoff-block-1",
            outbound_event_id="tg-handoff-block-1:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        second_reply = service.handle_client_message(
            session,
            external_chat_id="telegram:handoff-block",
            external_client_id="telegram-user:handoff-block",
            customer_name="Demo User",
            customer_text="а 14.023пр сколько осталось?",
            inbound_event_id="tg-handoff-block-2",
            outbound_event_id="tg-handoff-block-2:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert first_reply.handoff_reason == "client_requested_manager"
    assert second_reply.text == HANDOFF_ALREADY_REQUESTED_TEXT
    assert second_reply.handoff_reason is None

    with session_scope() as session:
        messages = session.query(Message).order_by(Message.id.asc()).all()
        handoffs = session.query(Handoff).all()

    assert len(handoffs) == 1
    assert messages[-1].sender_role == "bot"
    assert messages[-1].payload["source"] == "handoff_already_requested"
    assert not any(
        message.sender_role == "assistant_tool_call"
        and "search_products" in str(message.payload)
        and message.id > messages[3].id
        for message in messages
    )


def test_assistant_service_converts_text_only_handoff_to_real_action(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text="Передаю вопрос менеджеру. Он подключится к диалогу.",
        tool_calls=[],
    )

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:text-handoff",
            external_client_id="telegram-user:text-handoff",
            customer_name="Demo User",
            customer_text="помогите пожалуйста",
            inbound_event_id="tg-text-handoff",
            outbound_event_id="tg-text-handoff:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert reply.handoff_reason == "bot_uncertain"

    with session_scope() as session:
        handoffs = session.query(Handoff).all()
        messages = session.query(Message).order_by(Message.id.asc()).all()

    assert len(handoffs) == 1
    assert handoffs[0].reason == "bot_uncertain"
    assert [message.sender_role for message in messages] == ["client", "assistant_tool_call", "tool", "bot"]
    assert messages[1].payload["tool_calls"][0]["function"]["name"] == "handoff_to_manager"
    assert messages[2].payload["tool_name"] == "handoff_to_manager"
    assert messages[3].payload["backend_actions"]["handoff_to_manager_called"] is True


def test_assistant_service_answers_pending_consecutive_user_messages(isolated_app_env) -> None:
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

    service = AssistantService()
    service.openai_service.enabled = False

    with session_scope() as session:
        service.record_client_message(
            session,
            external_chat_id="telegram:pending-two",
            external_client_id="telegram-user:pending-two",
            customer_name="Demo User",
            customer_text="тогда проверьте 14.023пр",
            inbound_event_id="tg-pending-two-1",
            payload={"platform": "telegram"},
        )
        service.record_client_message(
            session,
            external_chat_id="telegram:pending-two",
            external_client_id="telegram-user:pending-two",
            customer_name="Demo User",
            customer_text="и xyz-999",
            inbound_event_id="tg-pending-two-2",
            payload={"platform": "telegram"},
        )
        reply = service.handle_pending_client_messages(
            session,
            external_chat_id="telegram:pending-two",
            outbound_event_id="tg-pending-two-2:bot",
            handoff_mode="demo",
        )

    assert "14.023пр" in reply.text
    assert "220 шт" in reply.text
    assert "xyz-999" in reply.text.lower()

    with session_scope() as session:
        messages = session.query(Message).order_by(Message.id.asc()).all()

    assert [message.sender_role for message in messages] == ["client", "client", "assistant_tool_call", "tool", "bot"]
    assert messages[-1].external_event_id == "tg-pending-two-2:bot"


def test_assistant_service_does_not_store_stale_llm_reply(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    current = {"value": True}

    def stale_llm_call(**kwargs):
        current["value"] = False
        return LLMTurnResult(text="Устаревший ответ", tool_calls=[])

    service.openai_service.run_messages = stale_llm_call

    with session_scope() as session:
        service.record_client_message(
            session,
            external_chat_id="telegram:stale-turn",
            external_client_id="telegram-user:stale-turn",
            customer_name="Demo User",
            customer_text="можете подсказать?",
            inbound_event_id="tg-stale-turn-1",
            payload={"platform": "telegram"},
        )
        reply = service.handle_pending_client_messages(
            session,
            external_chat_id="telegram:stale-turn",
            outbound_event_id="tg-stale-turn-1:bot",
            handoff_mode="demo",
            is_turn_current=lambda: current["value"],
        )

    assert reply.superseded is True
    assert reply.text == ""

    with session_scope() as session:
        messages = session.query(Message).order_by(Message.id.asc()).all()

    assert [message.sender_role for message in messages] == ["client"]


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


def test_assistant_service_uses_history_for_cheaper_followup(isolated_app_env) -> None:
    with session_scope() as session:
        for code, price, stock in (
            ("26167", "118", "124"),
            ("26168", "132", "292"),
            ("26169", "198", "237"),
        ):
            session.add(
                Product(
                    code=code,
                    article="МП 28ск",
                    normalized_article="МП28СК",
                    free_stock=Decimal(stock),
                    unit="шт.",
                    retail_price=Decimal(price),
                    raw_payload={},
                )
            )

    service = AssistantService()
    service.openai_service.enabled = False
    with session_scope() as session:
        service.handle_client_message(
            session,
            external_chat_id="telegram:cheaper",
            external_client_id="telegram-user:cheaper",
            customer_name="Demo User",
            customer_text="есть мп 28ск",
            inbound_event_id="tg-cheaper-1",
            outbound_event_id="tg-cheaper-1:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:cheaper",
            external_client_id="telegram-user:cheaper",
            customer_name="Demo User",
            customer_text="а есть мп дешевле?",
            inbound_event_id="tg-cheaper-2",
            outbound_event_id="tg-cheaper-2:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert reply.text != SAFE_FALLBACK_TEXT
    assert "МП 28ск" in reply.text
    assert "118 руб" in reply.text
    assert "132 руб" in reply.text
    assert "код 26167" in reply.text
    assert reply.handoff_reason is None


def test_assistant_service_refines_pending_variant_without_stale_history_queries(isolated_app_env) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="26141",
                article="1108035",
                normalized_article="1108035",
                free_stock=Decimal("2"),
                unit="компл",
                retail_price=Decimal("50820"),
                raw_payload={},
            )
        )
        for code, price, stock in (
            ("26167", "118", "124"),
            ("26168", "132", "292"),
            ("26169", "198", "237"),
        ):
            session.add(
                Product(
                    code=code,
                    article="МП 28ск",
                    normalized_article="МП28СК",
                    free_stock=Decimal(stock),
                    unit="шт.",
                    retail_price=Decimal(price),
                    raw_payload={},
                )
            )

    service = AssistantService()
    service.openai_service.enabled = False
    with session_scope() as session:
        service.handle_client_message(
            session,
            external_chat_id="telegram:refine-no-stale",
            external_client_id="telegram-user:refine-no-stale",
            customer_name="Demo User",
            customer_text="сколько стоит 1108035",
            inbound_event_id="tg-refine-stale-1",
            outbound_event_id="tg-refine-stale-1:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        service.handle_client_message(
            session,
            external_chat_id="telegram:refine-no-stale",
            external_client_id="telegram-user:refine-no-stale",
            customer_name="Demo User",
            customer_text="есть мп 28ск",
            inbound_event_id="tg-refine-stale-2",
            outbound_event_id="tg-refine-stale-2:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:refine-no-stale",
            external_client_id="telegram-user:refine-no-stale",
            customer_name="Demo User",
            customer_text="198 которая",
            inbound_event_id="tg-refine-stale-3",
            outbound_event_id="tg-refine-stale-3:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "237 шт" in reply.text
    assert "1108035" not in reply.text

    with session_scope() as session:
        tool_messages = (
            session.query(Message)
            .filter(Message.sender_role == "tool")
            .order_by(Message.id.asc())
            .all()
        )

    last_tool_payload = tool_messages[-1].payload["raw_product_lookup_result"]
    serialized = str(last_tool_payload)
    assert "1108035" not in serialized
    assert "50820" not in serialized
    assert last_tool_payload["exact_matches"][0]["code"] == "26169"


def test_assistant_service_sends_compact_tool_result_without_similar_when_exact_found(isolated_app_env) -> None:
    with session_scope() as session:
        session.add_all(
            [
                Product(
                    code="26141",
                    article="1108035",
                    normalized_article="1108035",
                    free_stock=Decimal("2"),
                    unit="компл",
                    retail_price=Decimal("50820"),
                    raw_payload={},
                ),
                Product(
                    code="26656",
                    article="1108036",
                    normalized_article="1108036",
                    free_stock=Decimal("1"),
                    unit="шт",
                    retail_price=Decimal("50820"),
                    raw_payload={},
                ),
            ]
        )

    service = AssistantService()
    service.openai_service.enabled = False
    with session_scope() as session:
        service.handle_client_message(
            session,
            external_chat_id="telegram:compact-tool",
            external_client_id="telegram-user:compact-tool",
            customer_name="Demo User",
            customer_text="1108035 сколько в наличии?",
            inbound_event_id="tg-compact-tool",
            outbound_event_id="tg-compact-tool:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    with session_scope() as session:
        tool_message = session.query(Message).filter(Message.sender_role == "tool").one()

    assert "similar_matches" not in tool_message.text
    assert "1108036" not in tool_message.text
    assert "тип" in tool_message.text
    assert "50 820" in tool_message.text
    raw_lookup = tool_message.payload["raw_product_lookup_result"]
    assert raw_lookup["similar_matches_count"] == 0
    assert raw_lookup["per_query_results"][0]["similar_matches_count"] == 0


def test_assistant_service_avoids_greeting_fallback_on_provider_error(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text=None,
        tool_calls=[],
        error_type="rate_limit_or_quota",
        retryable=True,
    )

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:provider-error",
            external_client_id="telegram-user:provider-error",
            customer_name="Demo User",
            customer_text="скидки есть?",
            inbound_event_id="tg-provider-error",
            outbound_event_id="tg-provider-error:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "Добрый день" not in reply.text
    assert "Подскажите, что нужно посмотреть" not in reply.text
    assert "задерживается" in reply.text


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


def test_assistant_service_can_disable_backend_prelookup_for_article_query(isolated_app_env, monkeypatch) -> None:
    monkeypatch.setenv("ASSISTANT_BACKEND_PRELOOKUP_ENABLED", "false")
    get_settings.cache_clear()

    with session_scope() as session:
        session.add(
            Product(
                code="1",
                article="AB-123",
                normalized_article="AB123",
                free_stock=Decimal("4"),
                unit="pcs",
                retail_price=Decimal("120"),
                corporate_price=Decimal("100"),
                raw_payload={},
            )
        )

    calls: list[dict] = []
    service = AssistantService()
    service.openai_service.enabled = True

    def fake_run_messages(**kwargs):
        calls.append(kwargs)
        if kwargs.get("tools"):
            return LLMTurnResult(
                text=None,
                tool_calls=[
                    ToolCall(
                        name="search_products",
                        call_id="call_search_ab123",
                        arguments={
                            "queries": ["AB-123"],
                            "intent": "price",
                            "use_dialog_context": False,
                        },
                    )
                ],
            )
        return LLMTurnResult(text="AB-123 costs 120 rub.", tool_calls=[])

    service.openai_service.run_messages = fake_run_messages

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:no-backend-prelookup",
            external_client_id="telegram-user:no-backend-prelookup",
            customer_name="Demo User",
            customer_text="What is the price for AB-123?",
            inbound_event_id="tg-no-backend-prelookup",
            outbound_event_id="tg-no-backend-prelookup:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        messages = session.query(Message).order_by(Message.id.asc()).all()

    assert reply.text == "AB-123 costs 120 rub."
    assert len(calls) == 2
    assert calls[0]["tool_choice"] == "auto"
    assert calls[0]["tools"]
    sources = [message.payload.get("source") for message in messages]
    assert "llm_tool_call" in sources
    assert "tool_result" in sources
    assert "llm_tool_search" in sources
    assert not any(str(source).startswith("backend_prelookup") for source in sources if source)


def test_assistant_service_keeps_full_tool_result_but_guards_stock_only_reply(
    isolated_app_env,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_BACKEND_PRELOOKUP_ENABLED", "false")
    get_settings.cache_clear()

    with session_scope() as session:
        session.add(
            Product(
                code="1",
                article="AB-123",
                normalized_article="AB123",
                free_stock=Decimal("4"),
                unit="pcs",
                retail_price=Decimal("120"),
                corporate_price=Decimal("100"),
                weight=Decimal("0.500"),
                raw_payload={},
            )
        )

    service = AssistantService()
    service.openai_service.enabled = True

    def fake_run_messages(**kwargs):
        if kwargs.get("tools"):
            return LLMTurnResult(
                text=None,
                tool_calls=[
                    ToolCall(
                        name="search_products",
                        call_id="call_stock_ab123",
                        arguments={
                            "queries": ["AB-123"],
                            "intent": "stock",
                            "use_dialog_context": False,
                        },
                    )
                ],
            )
        return LLMTurnResult(text="AB-123 costs 120 rub. Weight is 0.500 kg.", tool_calls=[])

    service.openai_service.run_messages = fake_run_messages

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:stock-only-tool-result",
            external_client_id="telegram-user:stock-only-tool-result",
            customer_name="Demo User",
            customer_text="\u0415\u0441\u0442\u044c AB-123?",
            inbound_event_id="tg-stock-only-tool-result",
            outbound_event_id="tg-stock-only-tool-result:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        tool_message = session.query(Message).filter(Message.sender_role == "tool").one()

    tool_content = tool_message.payload["content"]
    assert "120" in tool_content
    assert "0.500" in tool_content
    assert "120 rub" not in reply.text
    assert "4 pcs" in reply.text


def test_assistant_service_treats_plain_product_check_as_stock_only(
    isolated_app_env,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_BACKEND_PRELOOKUP_ENABLED", "false")
    get_settings.cache_clear()

    with session_scope() as session:
        session.add(
            Product(
                code="1",
                article="AB-123",
                normalized_article="AB123",
                free_stock=Decimal("4"),
                unit="pcs",
                retail_price=Decimal("120"),
                corporate_price=Decimal("100"),
                weight=Decimal("0.500"),
                raw_payload={},
            )
        )

    service = AssistantService()
    service.openai_service.enabled = True

    def fake_run_messages(**kwargs):
        if kwargs.get("tools"):
            return LLMTurnResult(
                text=None,
                tool_calls=[
                    ToolCall(
                        name="search_products",
                        call_id="call_check_ab123",
                        arguments={
                            "queries": ["AB-123", "ZZ-999"],
                            "intent": "product_info",
                            "use_dialog_context": False,
                        },
                    )
                ],
            )
        return LLMTurnResult(text="AB-123 costs 120 rub. Weight is 0.500 kg. ZZ-999 not found.", tool_calls=[])

    service.openai_service.run_messages = fake_run_messages

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:plain-check-stock-only",
            external_client_id="telegram-user:plain-check-stock-only",
            customer_name="Demo User",
            customer_text="Проверьте AB-123 и ZZ-999",
            inbound_event_id="tg-plain-check-stock-only",
            outbound_event_id="tg-plain-check-stock-only:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        tool_message = session.query(Message).filter(Message.sender_role == "tool").one()

    tool_content = tool_message.payload["content"]
    assert "120" in tool_content
    assert "0.500" in tool_content
    assert "120 rub" not in reply.text
    assert "0.500" not in reply.text
    assert "kg" not in reply.text.lower()
    assert "AB-123" in reply.text
    assert "ZZ-999" in reply.text


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
    assert "не могу безопасно подобрать" in reply.text
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
    assert "product_memory" in content
    assert "current_user_message" not in content
    assert any(message.get("role") == "tool" for message in captured["messages"])
    assert not any(str(message.get("content", "")).startswith("TOOL_RESULTS_JSON") for message in captured["messages"])


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
    assert "product_memory" in messages[1]["content"]
    assert "current_user_message" not in messages[1]["content"]
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


def test_assistant_service_converts_synthetic_tool_history_for_google_provider(isolated_app_env) -> None:
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
    service.openai_service.provider = "google_ai_studio"

    def fake_run_messages(**kwargs):
        captured["messages"] = kwargs["messages"]
        return LLMTurnResult(text="Проверил, остаток 220 шт.", tool_calls=[])

    service.openai_service.run_messages = fake_run_messages

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:google-tool-history",
            external_client_id="telegram-user:google-tool-history",
            customer_name="Demo User",
            customer_text="14.023пр есть?",
            inbound_event_id="tg-google-tool-history",
            outbound_event_id="tg-google-tool-history:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        stored_roles = [message.sender_role for message in session.query(Message).order_by(Message.id.asc()).all()]

    assert reply.text == "Проверил, остаток 220 шт."
    assert "assistant_tool_call" in stored_roles
    assert "tool" in stored_roles
    assert not any(message.get("role") == "tool" for message in captured["messages"])
    assert not any(message.get("tool_calls") for message in captured["messages"])
    assert any(
        message.get("role") == "system" and str(message.get("content", "")).startswith("TOOL_RESULTS_JSON")
        for message in captured["messages"]
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
    assert "не могу безопасно подобрать" in reply.text
    assert "подключится к диалогу" in reply.text


def test_complex_product_handoff_discards_llm_technical_guess(isolated_app_env) -> None:
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
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text="Эти товары отличаются стороной установки и являются зеркальными.",
        tool_calls=[],
    )

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:technical-guard",
            external_client_id="telegram-user:technical-guard",
            customer_name="Demo User",
            customer_text="чем 14.023л отличается от 14.023пр?",
            inbound_event_id="tg-technical-guard",
            outbound_event_id="tg-technical-guard:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert reply.handoff_reason == "complex_technical_question"
    assert "стороной установки" not in reply.text
    assert "зеркаль" not in reply.text.lower()
    assert "Технических характеристик" in reply.text
    assert "Передаю вопрос менеджеру" in reply.text


def test_assistant_service_routes_company_contact_question_to_llm_when_enabled(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    captured: dict = {}

    def fake_llm_call(**kwargs):
        captured["messages"] = kwargs["messages"]
        return LLMTurnResult(
            text="Мы находимся в Санкт-Петербурге, ул. Якорная, д. 15, лит. Б. Телефон: +7 (812) 372-66-07, почта market@amix.spb.ru.",
            tool_calls=[],
        )

    service.openai_service.run_messages = fake_llm_call

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
    assert "где вы находитесь и какой телефон?" in captured["messages"][-1]["content"]
    assert "safe_answer" in captured["messages"][-1]["content"]

    with session_scope() as session:
        bot_message = session.query(Message).filter(Message.sender_role == "bot").one()

    assert bot_message.payload["source"] == "llm_company_faq"


def test_assistant_service_allows_company_faq_polite_rewrite(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True

    def polite_llm_call(**kwargs):
        return LLMTurnResult(
            text="Наш магазин находится в Санкт-Петербурге на улице Якорной, дом 15, литера Б. Будем рады видеть вас!",
            tool_calls=[],
        )

    service.openai_service.run_messages = polite_llm_call

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:company-address-guard",
            external_client_id="telegram-user:company-address-guard",
            customer_name="Demo User",
            customer_text="а где вы находитесь",
            inbound_event_id="tg-company-address-guard",
            outbound_event_id="tg-company-address-guard:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "Будем рады" in reply.text
    assert "Санкт-Петербурге" in reply.text
    assert "Якорной" in reply.text

    with session_scope() as session:
        bot_message = session.query(Message).filter(Message.sender_role == "bot").one()

    assert bot_message.payload["source"] == "llm_company_faq"


def test_assistant_service_guards_company_self_description_from_bot_capabilities(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True

    def unsafe_llm_call(**kwargs):
        return LLMTurnResult(
            text="Я интеллектуальный помощник AMIX. Подскажу характеристики, размеры, совместимость и аналоги.",
            tool_calls=[],
        )

    service.openai_service.run_messages = unsafe_llm_call

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:company-self",
            external_client_id="telegram-user:company-self",
            customer_name="Demo User",
            customer_text="вы расскажите о себе",
            inbound_event_id="tg-company-self",
            outbound_event_id="tg-company-self:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "AMIX - магазин и поставщик мебельной фурнитуры" in reply.text
    assert "интеллектуальный помощник" not in reply.text.lower()
    assert "характеристики" not in reply.text.lower()

    with session_scope() as session:
        bot_message = session.query(Message).filter(Message.sender_role == "bot").one()

    assert bot_message.payload["source"] == "backend_company_faq_guard"


def test_assistant_service_uses_company_faq_only_when_llm_disabled(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = False

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

    with session_scope() as session:
        bot_message = session.query(Message).filter(Message.sender_role == "bot").one()

    assert bot_message.payload["source"] == "backend_company_faq"


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


def test_assistant_service_resolves_second_product_followup_by_user_query_order(isolated_app_env) -> None:
    with session_scope() as session:
        session.add_all(
            [
                Product(
                    code="770",
                    article="14.023пр.",
                    normalized_article=normalize_article("14.023пр."),
                    free_stock=Decimal("220"),
                    unit="шт",
                    retail_price=Decimal("473"),
                    raw_payload={},
                ),
                Product(
                    code="22608",
                    article="P-AM02/B-S",
                    normalized_article=normalize_article("P-AM02/B-S"),
                    free_stock=Decimal("1"),
                    unit="шт",
                    retail_price=Decimal("1000"),
                    raw_payload={},
                ),
            ]
        )

    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(text="Проверил.", tool_calls=[])

    with session_scope() as session:
        service.handle_client_message(
            session,
            external_chat_id="telegram:query-order",
            external_client_id="telegram-user:query-order",
            customer_name="Demo User",
            customer_text="нужно мне наличие узнать 14.023пр и p am02 b s",
            inbound_event_id="tg-order-1",
            outbound_event_id="tg-order-1:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:query-order",
            external_client_id="telegram-user:query-order",
            customer_name="Demo User",
            customer_text="а по второму",
            inbound_event_id="tg-order-2",
            outbound_event_id="tg-order-2:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        bot_messages = session.query(Message).filter(Message.sender_role == "bot").order_by(Message.id.asc()).all()

    second_lookup = bot_messages[-1].payload["product_lookup_result"]
    assert reply.text == "Проверил."
    assert second_lookup["exact_matches"][0]["article"] == "P-AM02/B-S"
    assert second_lookup["exact_matches"][0]["code"] == "22608"


def test_assistant_service_resolves_fragment_followup_from_previous_lookup(isolated_app_env) -> None:
    with session_scope() as session:
        session.add_all(
            [
                Product(
                    code="770",
                    article="14.023пр.",
                    normalized_article=normalize_article("14.023пр."),
                    free_stock=Decimal("220"),
                    unit="шт",
                    retail_price=Decimal("473"),
                    raw_payload={},
                ),
                Product(
                    code="22608",
                    article="P-AM02/B-S",
                    normalized_article=normalize_article("P-AM02/B-S"),
                    free_stock=Decimal("1"),
                    unit="шт",
                    retail_price=Decimal("1000"),
                    raw_payload={},
                ),
            ]
        )

    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(text="Проверил.", tool_calls=[])

    with session_scope() as session:
        service.handle_client_message(
            session,
            external_chat_id="telegram:fragment-followup",
            external_client_id="telegram-user:fragment-followup",
            customer_name="Demo User",
            customer_text="нужно мне наличие узнать 14.023пр и p am02 b s",
            inbound_event_id="tg-fragment-1",
            outbound_event_id="tg-fragment-1:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        service.handle_client_message(
            session,
            external_chat_id="telegram:fragment-followup",
            external_client_id="telegram-user:fragment-followup",
            customer_name="Demo User",
            customer_text="так я про второй спрашиваю am02 который я написал",
            inbound_event_id="tg-fragment-2",
            outbound_event_id="tg-fragment-2:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        bot_messages = session.query(Message).filter(Message.sender_role == "bot").order_by(Message.id.asc()).all()

    second_lookup = bot_messages[-1].payload["product_lookup_result"]
    assert second_lookup["exact_matches"][0]["article"] == "P-AM02/B-S"
    assert second_lookup["exact_matches"][0]["code"] == "22608"


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


def test_assistant_service_does_not_show_corporate_price_without_request(isolated_app_env) -> None:
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
            external_chat_id="telegram:no-corp-by-default",
            external_client_id="telegram-user:no-corp-by-default",
            customer_name="Demo User",
            customer_text="Сколько стоит 14.025пр.?",
            inbound_event_id="tg-no-corp-by-default",
            outbound_event_id="tg-no-corp-by-default:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "Розничная цена 238 руб." in reply.text
    assert "Корпоративная" not in reply.text


def test_assistant_service_shows_corporate_price_when_requested(isolated_app_env) -> None:
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
            external_chat_id="telegram:corp-request",
            external_client_id="telegram-user:corp-request",
            customer_name="Demo User",
            customer_text="Корпоративная цена 14.025пр.?",
            inbound_event_id="tg-corp-request",
            outbound_event_id="tg-corp-request:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "Корпоративная цена 165,98 руб." in reply.text


def test_assistant_service_uses_product_fallback_on_provider_timeout(isolated_app_env) -> None:
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

    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text=None,
        tool_calls=[],
        error_type="timeout",
        retryable=True,
    )

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:provider-timeout-product",
            external_client_id="telegram-user:provider-timeout-product",
            customer_name="Demo User",
            customer_text="Проверьте 14.023пр.",
            inbound_event_id="tg-provider-timeout-product",
            outbound_event_id="tg-provider-timeout-product:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "14.023пр" in reply.text
    assert "220 шт" in reply.text
    assert "Подскажите, что нужно посмотреть" not in reply.text


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


def test_assistant_service_sanitizes_link_or_photo_request() -> None:
    text = AssistantService._sanitize_customer_reply(  # noqa: SLF001
        "Пришлите ссылку или фото, чтобы я уточнил позицию."
    )

    assert "ссылку" not in text.lower()
    assert "фото" not in text.lower()
    assert "код товара с сайта или цену в карточке" in text


def test_assistant_service_sanitizes_internal_search_and_database_phrasing() -> None:
    text = AssistantService._sanitize_customer_reply(  # noqa: SLF001
        "Для проверки наличия товаров мне нужно воспользоваться поиском.\n"
        "В нашей базе данных по артикулу есть 2 шт."
    )

    assert "воспользоваться поиском" not in text
    assert "базе данных" not in text
    assert "в текущих данных" in text


def test_assistant_service_marks_currency_suffix_as_price_refinement() -> None:
    assert AssistantService._looks_like_price_refinement("194р", [])  # noqa: SLF001
    assert AssistantService._looks_like_price_refinement("194 руб", [])  # noqa: SLF001


def test_assistant_service_extracts_named_digitless_product_query() -> None:
    query = AssistantService._extract_named_product_query("МП ЦК белая она сколько весит")  # noqa: SLF001

    assert query == "МП ЦК белая"


def test_assistant_service_detects_unknown_codes_in_llm_reply() -> None:
    lookup = {
        "exact_matches": [
            {"code": "32107", "article": "МП/ОЗ"},
            {"code": "32108", "article": "МП/ОЗ"},
        ],
        "similar_matches": [],
    }

    assert AssistantService._reply_mentions_unknown_product_codes("Код 27790: МП/ЦК белая", lookup)  # noqa: SLF001
    assert not AssistantService._reply_mentions_unknown_product_codes("Код 32107: МП/ОЗ", lookup)  # noqa: SLF001


def test_assistant_service_keeps_prices_for_stock_only_context() -> None:
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
    assert match["retail_price"] == "50820.00"
    assert match["retail_price_display"] == "50 820 руб."
    assert match["corporate_price"] == "24283.00"
    assert match["corporate_price_display"] == "24 283 руб."


def test_assistant_service_searches_explicit_digitless_slash_article_instead_of_previous_active_product(
    isolated_app_env,
) -> None:
    with session_scope() as session:
        session.add_all(
            [
                Product(
                    code="26141",
                    article="1108035",
                    normalized_article=normalize_article("1108035"),
                    free_stock=Decimal("2"),
                    unit="компл",
                    retail_price=Decimal("50820"),
                    weight=None,
                    raw_payload={},
                ),
                Product(
                    code="27817",
                    article="МП/ОЗ",
                    normalized_article=normalize_article("МП/ОЗ"),
                    free_stock=Decimal("33"),
                    unit="шт",
                    retail_price=Decimal("1299"),
                    weight=Decimal("1.760"),
                    raw_payload={},
                ),
                Product(
                    code="27818",
                    article="МП/ОЗ",
                    normalized_article=normalize_article("МП/ОЗ"),
                    free_stock=Decimal("219"),
                    unit="шт",
                    retail_price=Decimal("1150"),
                    weight=Decimal("2.160"),
                    raw_payload={},
                ),
            ]
        )

    service = AssistantService()
    service.openai_service.enabled = False

    with session_scope() as session:
        service.handle_client_message(
            session,
            external_chat_id="telegram:mpoz-weight",
            external_client_id="telegram-user:mpoz-weight",
            customer_name="Demo User",
            customer_text="26141 какая цена",
            inbound_event_id="tg-mpoz-weight-1",
            outbound_event_id="tg-mpoz-weight-1:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:mpoz-weight",
            external_client_id="telegram-user:mpoz-weight",
            customer_name="Demo User",
            customer_text="МП/ОЗ у него какая масса?",
            inbound_event_id="tg-mpoz-weight-2",
            outbound_event_id="tg-mpoz-weight-2:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "МП/ОЗ" in reply.text
    assert "1.76 кг" in reply.text
    assert "2.16 кг" in reply.text
    assert "1108035" not in reply.text


def test_assistant_service_searches_named_digitless_product_instead_of_previous_article(
    isolated_app_env,
) -> None:
    with session_scope() as session:
        session.add_all(
            [
                Product(
                    code="32107",
                    article="МП/ОЗ",
                    normalized_article=normalize_article("МП/ОЗ"),
                    free_stock=Decimal("15"),
                    unit="компл",
                    retail_price=Decimal("37"),
                    weight=Decimal("0.060"),
                    raw_payload={},
                ),
                Product(
                    code="28834",
                    article="МП ЦК белая",
                    normalized_article=normalize_article("МП ЦК белая"),
                    free_stock=Decimal("39"),
                    unit="шт",
                    retail_price=Decimal("314"),
                    weight=Decimal("0.538"),
                    raw_payload={},
                ),
            ]
        )

    service = AssistantService()
    service.openai_service.enabled = False

    with session_scope() as session:
        service.handle_client_message(
            session,
            external_chat_id="telegram:mpck-weight",
            external_client_id="telegram-user:mpck-weight",
            customer_name="Demo User",
            customer_text="МП/ОЗ какая масса?",
            inbound_event_id="tg-mpck-weight-1",
            outbound_event_id="tg-mpck-weight-1:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:mpck-weight",
            external_client_id="telegram-user:mpck-weight",
            customer_name="Demo User",
            customer_text="МП ЦК белая она сколько весит",
            inbound_event_id="tg-mpck-weight-2",
            outbound_event_id="tg-mpck-weight-2:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )

    assert "МП ЦК белая" in reply.text
    assert "0.538 кг" in reply.text
    assert "МП/ОЗ" not in reply.text


def test_assistant_service_uses_pending_lookup_for_currency_price_refinement(
    isolated_app_env,
) -> None:
    with session_scope() as session:
        session.add_all(
            [
                Product(
                    code="32107",
                    article="МП/ОЗ",
                    normalized_article=normalize_article("МП/ОЗ"),
                    free_stock=Decimal("15"),
                    unit="компл",
                    retail_price=Decimal("37"),
                    weight=Decimal("0.060"),
                    raw_payload={},
                ),
                Product(
                    code="32108",
                    article="МП/ОЗ",
                    normalized_article=normalize_article("МП/ОЗ"),
                    free_stock=Decimal("18"),
                    unit="компл",
                    retail_price=Decimal("73"),
                    weight=Decimal("0.012"),
                    raw_payload={},
                ),
            ]
        )

    service = AssistantService()
    service.openai_service.enabled = False

    with session_scope() as session:
        service.handle_client_message(
            session,
            external_chat_id="telegram:mpoz-price-refine",
            external_client_id="telegram-user:mpoz-price-refine",
            customer_name="Demo User",
            customer_text="МП/ОЗ какая масса?",
            inbound_event_id="tg-mpoz-price-refine-1",
            outbound_event_id="tg-mpoz-price-refine-1:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:mpoz-price-refine",
            external_client_id="telegram-user:mpoz-price-refine",
            customer_name="Demo User",
            customer_text="который 194р стоит",
            inbound_event_id="tg-mpoz-price-refine-2",
            outbound_event_id="tg-mpoz-price-refine-2:bot",
            payload={"platform": "telegram"},
            handoff_mode="demo",
        )
        last_bot = session.query(Message).order_by(Message.id.desc()).first()

    assert "МП/ОЗ" in reply.text
    assert "194р" not in (last_bot.payload["product_lookup_result"]["display_query"] or "")
    assert last_bot.payload["product_lookup_result"]["display_query"] == "МП/ОЗ"


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
