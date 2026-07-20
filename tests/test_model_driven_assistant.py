import json
from decimal import Decimal

import database.models as database_models
import llm.prompts as prompt_module
import products.article_utils as article_utils
from core.assistant_service import AssistantService
from database.db import session_scope
from database.models import Handoff, Message, Product
from llm.openai_client import LLMTurnResult, OpenAIService, ToolCall
from llm.prompts import SYSTEM_PROMPT, build_llm_messages
from llm.tool_schemas import OPENAI_TOOLS
from products.article_utils import normalize_article
from settings import get_settings


def _tool_names(tools: list[dict]) -> list[str]:
    return [tool["function"]["name"] for tool in tools]


def test_enabled_llm_never_uses_backend_semantic_router(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True

    assert not hasattr(service, "_extract_named_product_query")
    assert not hasattr(service, "_is_explicit_manager_request")
    assert not hasattr(service.handoff_service, "evaluate")
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text="Уточните, пожалуйста, ваш вопрос.",
        tool_calls=[],
    )

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:model-only-router",
            external_client_id="telegram-user:model-only-router",
            customer_name="Ирина",
            customer_text="хочу кое-что уточнить по прошлому сообщению",
            inbound_event_id="model-only-router-in",
            outbound_event_id="model-only-router-out",
            payload={},
            handoff_mode="demo",
        )

    assert reply.text == "Уточните, пожалуйста, ваш вопрос."


def test_every_model_round_receives_only_two_tools_and_chronological_result(isolated_app_env) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="770",
                article="14.023пр.",
                normalized_article=normalize_article("14.023пр."),
                retail_price=Decimal("473"),
                corporate_price=Decimal("410"),
                free_stock=Decimal("220"),
                unit="шт",
                weight=Decimal("0.070"),
                raw_payload={},
            )
        )

    service = AssistantService()
    service.openai_service.enabled = True
    requests: list[dict] = []

    def fake_model(**kwargs):
        requests.append(kwargs)
        if not any(message.get("role") == "tool" for message in kwargs["messages"]):
            return LLMTurnResult(
                text=None,
                tool_calls=[
                    ToolCall(
                        name="search_products",
                        arguments={"queries": [{"query": "14.023пр", "requested_quantity": 2}]},
                        call_id="search-770",
                        thought_signature="encrypted-google-signature",
                    )
                ],
            )
        return LLMTurnResult(text="Да, две штуки доступны.", tool_calls=[])

    service.openai_service.run_messages = fake_model

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:two-tools-every-round",
            external_client_id="telegram-user:two-tools-every-round",
            customer_name="Ирина",
            customer_text="14.023пр нужно две штуки",
            inbound_event_id="two-tools-every-round-in",
            outbound_event_id="two-tools-every-round-out",
            payload={},
            handoff_mode="demo",
        )
        stored_roles = [
            message.sender_role
            for message in session.query(Message).order_by(Message.id.asc()).all()
        ]

    assert reply.text == "Да, две штуки доступны."
    assert len(requests) == 2
    assert all(_tool_names(request["tools"]) == ["search_products", "handoff_to_manager"] for request in requests)
    second_dialog = [message for message in requests[1]["messages"] if message["role"] != "system"]
    assert [message["role"] for message in second_dialog] == ["user", "assistant", "tool"]
    assert second_dialog[1]["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "encrypted-google-signature"}
    }
    tool_payload = json.loads(second_dialog[-1]["content"])
    product = tool_payload["result"]["results"][0]["exact_matches"][0]
    assert product["stock"] == "220.000"
    assert product["retail_price"] == "473.00"
    assert product["corporate_price"] == "410.00"
    assert product["weight"] == "0.070"
    assert tool_payload["result"]["results"][0]["requested_quantity_available"] is True
    assert stored_roles == ["client", "assistant_tool_call", "tool", "bot"]


def test_model_handoff_tool_is_executed_without_keyword_confirmation(isolated_app_env) -> None:
    service = AssistantService()
    service.openai_service.enabled = True
    service.openai_service.run_messages = lambda **kwargs: LLMTurnResult(
        text=None,
        tool_calls=[
            ToolCall(
                name="handoff_to_manager",
                arguments={
                    "reason": "technical_consultation",
                    "summary": "Клиенту нужна техническая консультация.",
                    "customer_message": "Передаю вопрос менеджеру. Он подключится к диалогу.",
                },
                call_id="handoff-technical",
            )
        ],
    )

    with session_scope() as session:
        reply = service.handle_client_message(
            session,
            external_chat_id="telegram:model-handoff",
            external_client_id="telegram-user:model-handoff",
            customer_name="Ирина",
            customer_text="нужна консультация по этой детали",
            inbound_event_id="model-handoff-in",
            outbound_event_id="model-handoff-out",
            payload={},
            handoff_mode="demo",
        )
        handoffs = session.query(Handoff).all()

    assert reply.handoff_reason == "technical_consultation"
    assert len(handoffs) == 1


def test_search_tool_schema_does_not_require_backend_intent_classification() -> None:
    search_tool = next(tool for tool in OPENAI_TOOLS if tool["function"]["name"] == "search_products")
    parameters = search_tool["function"]["parameters"]

    assert parameters["required"] == ["queries"]
    assert set(parameters["properties"]) == {"queries"}


def test_single_prompt_owns_dialog_order_and_handoff_semantics() -> None:
    prompt = SYSTEM_PROMPT.lower()

    assert "полная хронологическая история" in prompt
    assert "requested_quantity" in prompt
    assert "точный свободный остаток" in prompt
    assert "reason=order_creation" in prompt
    assert "явного подтверждения" in prompt
    assert "не блокирует сбор заявки" in prompt
    assert "не заменяй его своим предположением" in prompt
    assert "не больше двух связанных вопросов" in prompt
    assert "считай это поле собранным" in prompt
    assert "не проверяешь реализуемость сочетания условий" in prompt
    assert "не является причиной для немедленной передачи менеджеру" in prompt
    assert "update_order_draft" not in prompt
    assert "order_draft" not in prompt


def test_prompt_requires_natural_varied_conversation_without_scripted_fillers() -> None:
    prompt = SYSTEM_PROMPT.lower()

    assert "реагируй на смысл сообщения" in prompt
    assert "варьируй начала фраз и ритм" in prompt
    assert "не повторяй одни и те же вводные" in prompt
    assert "разговорные связки и частицы" in prompt
    assert "не вставляй их механически" in prompt
    assert "словами-паразитами" in prompt
    assert "подстраивай длину и тон" in prompt
    assert "не зеркаль вопрос клиента" in prompt
    assert "через ясный полезный ответ" in prompt
    assert "не подтверждай каждое полученное поле" in prompt
    assert "с одного ближайшего шага" in prompt
    assert "не перечисляй сразу все оставшиеся вопросы" in prompt
    assert "одинаковую структуру" in prompt
    assert "служебное подтверждение уже понятного ответа чаще пропускай" in prompt
    assert "одно сообщение - один шаг разговора" in prompt


def test_prompt_builder_only_combines_policy_and_chronological_history() -> None:
    messages = build_llm_messages(
        dialog_messages=[
            {"role": "user", "content": "тест"},
            {"role": "assistant", "content": "Уточните товар."},
            {"role": "user", "content": "Сравните два товара"},
        ],
    )

    assert [message["role"] for message in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "тест"
    assert messages[3]["content"] == "Сравните два товара"
    serialized = json.dumps(messages, ensure_ascii=False)
    assert "INTERNAL_CONTEXT_JSON" not in serialized
    assert "TOOL_RESULTS_JSON" not in serialized
    assert "backend_actions" not in serialized


def test_prompt_module_has_no_alternate_behavior_builders() -> None:
    assert not hasattr(prompt_module, "PRODUCT_FACTS_RESPONSE_PROMPT")
    assert not hasattr(prompt_module, "COMPANY_FAQ_REWRITE_PROMPT")
    assert not hasattr(prompt_module, "build_product_facts_messages")
    assert not hasattr(prompt_module, "build_company_faq_messages")
    assert not hasattr(OpenAIService, "generate_reply")


def test_runtime_configuration_has_no_legacy_semantic_router_switches() -> None:
    settings = get_settings()

    assert not hasattr(settings, "assistant_backend_prelookup_enabled")
    assert not hasattr(settings, "assistant_deterministic_company_faq_enabled")
    assert not hasattr(database_models, "OrderDraft")
    assert not hasattr(article_utils, "extract_article_candidates")
