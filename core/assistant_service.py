from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import Any

from database.repositories import (
    append_message,
    get_or_create_chat,
    get_or_create_customer,
    get_product_by_article,
    get_similar_products,
    search_products_structured,
)
from llm.openai_client import OpenAIService
from llm.prompts import build_llm_messages, build_product_facts_messages
from llm.tool_schemas import OPENAI_TOOLS
from products.article_utils import extract_article_candidates
from products.product_search import ProductSearchService
from settings import get_settings

from .dialog_service import DialogService
from .handoff_service import HandoffService


logger = logging.getLogger(__name__)


SAFE_FALLBACK_TEXT = (
    "Я могу проверить по базе артикул, код, свободный остаток, цену, единицу измерения, вес и объём. "
    "Если пришлёте артикул или код, сразу посмотрю данные. "
    "Если нужен подбор, аналог или техническая консультация, лучше передать вопрос менеджеру."
)

JIVO_HANDOFF_TEXT = "Передаю ваш вопрос менеджеру."

TELEGRAM_DEMO_HANDOFF_TEXT = (
    "Этот вопрос требует менеджера. В рабочем режиме я бы передал диалог оператору. "
    "В демо-режиме могу продолжить только по артикулам, кодам, наличию, остаткам и ценам."
)

ARTICLE_REQUIRED_TEXT = (
    "Чтобы проверить наличие, остаток или цену, пришлите артикул или код товара. "
    "По текущей базе я могу проверить артикул, код, остаток, цену, единицу измерения, вес и объём."
)


@dataclass(slots=True)
class AssistantReply:
    text: str
    handoff_reason: str | None = None


class AssistantService:
    def __init__(self) -> None:
        settings = get_settings()
        self.dialog_service = DialogService(history_limit=settings.history_limit)
        self.handoff_service = HandoffService()
        self.openai_service = OpenAIService(settings)
        self.product_search = ProductSearchService()
        self.debug_lookup_logs = settings.assistant_debug_lookup_logs

    def handle_client_message(
        self,
        session,
        *,
        external_chat_id: str,
        external_client_id: str,
        customer_name: str | None,
        customer_text: str,
        inbound_event_id: str | None,
        outbound_event_id: str | None,
        payload: dict | None = None,
        handoff_mode: str = "jivo",
    ) -> AssistantReply:
        customer = get_or_create_customer(
            session,
            external_client_id=external_client_id,
            name=customer_name,
        )
        chat = get_or_create_chat(session, external_chat_id, customer.id)

        append_message(
            session,
            external_chat_id=chat.external_chat_id,
            sender_role="client",
            text=customer_text,
            external_event_id=inbound_event_id,
            payload=payload or {},
        )

        if self.openai_service.enabled:
            return self._handle_via_backend_first_llm(
                session,
                external_chat_id=chat.external_chat_id,
                customer_text=customer_text,
                outbound_event_id=outbound_event_id,
                handoff_mode=handoff_mode,
            )

        return self._handle_via_legacy_fallback(
            session,
            external_chat_id=chat.external_chat_id,
            customer_text=customer_text,
            outbound_event_id=outbound_event_id,
            handoff_mode=handoff_mode,
        )

    def _handle_via_backend_first_llm(
        self,
        session,
        *,
        external_chat_id: str,
        customer_text: str,
        outbound_event_id: str | None,
        handoff_mode: str,
    ) -> AssistantReply:
        transcript = self.dialog_service.get_transcript(session, external_chat_id)

        if self._is_explicit_manager_request(customer_text):
            return self._handoff_reply(
                session,
                external_chat_id=external_chat_id,
                handoff_mode=handoff_mode,
                outbound_event_id=outbound_event_id,
                reason="client_requested_manager",
                source="backend_rule",
            )

        prelookup_result = self._run_backend_prelookup(session, customer_text)
        if prelookup_result is not None:
            self._log_lookup_result(stage="prelookup", payload=prelookup_result)
            return self._reply_from_product_result(
                session,
                external_chat_id=external_chat_id,
                customer_text=customer_text,
                transcript=transcript,
                product_lookup_result=prelookup_result,
                outbound_event_id=outbound_event_id,
                payload_source="backend_prelookup",
            )

        messages = build_llm_messages(
            transcript=transcript,
            customer_text=customer_text,
            product_lookup_result=None,
        )
        first_turn = self.openai_service.run_messages(messages=messages, tools=OPENAI_TOOLS, tool_choice="auto")
        self._log_tool_turn(customer_text=customer_text, turn=first_turn)

        if first_turn.tool_calls:
            tool_reply = self._handle_tool_calls(
                session,
                external_chat_id=external_chat_id,
                customer_text=customer_text,
                transcript=transcript,
                tool_calls=first_turn.tool_calls,
                outbound_event_id=outbound_event_id,
                handoff_mode=handoff_mode,
            )
            if tool_reply is not None:
                return tool_reply

        if first_turn.text:
            self._append_bot_message(
                session,
                external_chat_id=external_chat_id,
                text=first_turn.text,
                outbound_event_id=outbound_event_id,
                payload={"source": "llm_direct"},
            )
            return AssistantReply(text=first_turn.text)

        if self._is_price_stock_request(customer_text):
            self._append_bot_message(
                session,
                external_chat_id=external_chat_id,
                text=ARTICLE_REQUIRED_TEXT,
                outbound_event_id=outbound_event_id,
                payload={"source": "fallback", "mode": "article_required"},
            )
            return AssistantReply(text=ARTICLE_REQUIRED_TEXT)

        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=SAFE_FALLBACK_TEXT,
            outbound_event_id=outbound_event_id,
            payload={"source": "fallback"},
        )
        return AssistantReply(text=SAFE_FALLBACK_TEXT)

    def _handle_tool_calls(
        self,
        session,
        *,
        external_chat_id: str,
        customer_text: str,
        transcript: str,
        tool_calls: list,
        outbound_event_id: str | None,
        handoff_mode: str,
    ) -> AssistantReply | None:
        for call in tool_calls:
            if call.name == "handoff_to_manager":
                reason = str(call.arguments.get("reason") or "llm_requested_manager")
                return self._handoff_reply(
                    session,
                    external_chat_id=external_chat_id,
                    handoff_mode=handoff_mode,
                    outbound_event_id=outbound_event_id,
                    reason=reason,
                    source="llm_tool",
                )

            if call.name != "search_products":
                continue

            queries = call.arguments.get("queries", [])
            if not isinstance(queries, list):
                queries = []
            queries = [str(item).strip() for item in queries if str(item).strip()]
            if not queries:
                continue

            lookup = self._search_products_by_queries(session, queries=queries, reason=str(call.arguments.get("reason") or "unknown"))
            self._log_lookup_result(stage="tool_call", payload=lookup)
            return self._reply_from_product_result(
                session,
                external_chat_id=external_chat_id,
                customer_text=customer_text,
                transcript=transcript,
                product_lookup_result=lookup,
                outbound_event_id=outbound_event_id,
                payload_source="llm_tool_search",
            )
        return None

    def _reply_from_product_result(
        self,
        session,
        *,
        external_chat_id: str,
        customer_text: str,
        transcript: str,
        product_lookup_result: dict,
        outbound_event_id: str | None,
        payload_source: str,
    ) -> AssistantReply:
        fact_messages = build_product_facts_messages(
            transcript=transcript,
            customer_text=customer_text,
            product_lookup_result=product_lookup_result,
        )
        turn = self.openai_service.run_messages(messages=fact_messages)
        reply_text = turn.text or self._build_programmatic_lookup_fallback(product_lookup_result)

        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=reply_text,
            outbound_event_id=outbound_event_id,
            payload={
                "source": payload_source,
                "product_lookup_status": product_lookup_result.get("status"),
                "exact_matches_count": product_lookup_result.get("exact_matches_count"),
                "similar_matches_count": product_lookup_result.get("similar_matches_count"),
            },
        )
        return AssistantReply(text=reply_text)

    def _run_backend_prelookup(self, session, customer_text: str) -> dict[str, Any] | None:
        candidates = extract_article_candidates(customer_text)
        if not candidates:
            return None
        reason = self._guess_lookup_reason(customer_text)
        return self._search_products_by_queries(session, queries=candidates, reason=reason)

    def _search_products_by_queries(self, session, *, queries: list[str], reason: str) -> dict:
        per_query_results: list[dict] = []
        best: dict | None = None
        priority = {
            "multiple_exact": 0,
            "exact_found": 1,
            "similar_found": 2,
            "not_found": 3,
            "invalid_query": 4,
            "error": 5,
        }

        for query in queries:
            item = search_products_structured(session, query=query, search_type="auto")
            per_query_results.append(item)
            if best is None:
                best = item
                continue
            if priority.get(item["status"], 99) < priority.get(best["status"], 99):
                best = item

        if best is None:
            return {
                "queries": queries,
                "reason": reason,
                "status": "invalid_query",
                "exact_matches_count": 0,
                "similar_matches_count": 0,
                "exact_matches": [],
                "similar_matches": [],
                "backend_notes": ["No valid queries"],
            }

        return {
            "queries": queries,
            "reason": reason,
            **best,
            "per_query_results": per_query_results,
        }

    def _handoff_reply(
        self,
        session,
        *,
        external_chat_id: str,
        handoff_mode: str,
        outbound_event_id: str | None,
        reason: str,
        source: str,
    ) -> AssistantReply:
        self.handoff_service.register_handoff(session, external_chat_id, reason)
        handoff_text = self._resolve_handoff_text(handoff_mode)
        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=handoff_text,
            outbound_event_id=outbound_event_id,
            payload={"source": source, "handoff_reason": reason},
        )
        return AssistantReply(text=handoff_text, handoff_reason=reason)

    def _handle_via_legacy_fallback(
        self,
        session,
        *,
        external_chat_id: str,
        customer_text: str,
        outbound_event_id: str | None,
        handoff_mode: str,
    ) -> AssistantReply:
        handoff_decision = self.handoff_service.evaluate(customer_text)
        if handoff_decision.should_handoff and handoff_decision.reason:
            return self._handoff_reply(
                session,
                external_chat_id=external_chat_id,
                handoff_mode=handoff_mode,
                outbound_event_id=outbound_event_id,
                reason=handoff_decision.reason,
                source="legacy",
            )

        article_candidates = extract_article_candidates(customer_text)
        if not article_candidates and self._is_price_stock_request(customer_text):
            self._append_bot_message(
                session,
                external_chat_id=external_chat_id,
                text=ARTICLE_REQUIRED_TEXT,
                outbound_event_id=outbound_event_id,
                payload={"source": "legacy", "mode": "clarify"},
            )
            return AssistantReply(text=ARTICLE_REQUIRED_TEXT)

        for candidate in article_candidates:
            product = get_product_by_article(session, candidate)
            if product is not None:
                reply_text = self.product_search.build_product_reply(product)
                self._append_bot_message(
                    session,
                    external_chat_id=external_chat_id,
                    text=reply_text,
                    outbound_event_id=outbound_event_id,
                    payload={"matched_article": candidate, "source": "legacy"},
                )
                return AssistantReply(text=reply_text)

        if article_candidates:
            requested_article = article_candidates[0]
            similar_products = get_similar_products(session, requested_article, limit=5)
            if similar_products:
                reply_text = self.product_search.build_similar_products_reply(requested_article, similar_products)
                self._append_bot_message(
                    session,
                    external_chat_id=external_chat_id,
                    text=reply_text,
                    outbound_event_id=outbound_event_id,
                    payload={"similar_for": requested_article, "source": "legacy"},
                )
                return AssistantReply(text=reply_text)

            reply_text = (
                f"Не нашёл артикул {requested_article} в текущей выгрузке. "
                "Проверьте написание артикула. "
                "Если нужен подбор или аналог, лучше передать вопрос менеджеру."
            )
            self._append_bot_message(
                session,
                external_chat_id=external_chat_id,
                text=reply_text,
                outbound_event_id=outbound_event_id,
                payload={"missing_article": requested_article, "source": "legacy"},
            )
            return AssistantReply(text=reply_text)

        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=SAFE_FALLBACK_TEXT,
            outbound_event_id=outbound_event_id,
            payload={"source": "legacy_fallback"},
        )
        return AssistantReply(text=SAFE_FALLBACK_TEXT)

    @staticmethod
    def _is_explicit_manager_request(customer_text: str) -> bool:
        text = customer_text.lower()
        keywords = ("менеджер", "оператор", "человек", "перезвон", "позвон")
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _is_price_stock_request(customer_text: str) -> bool:
        text = customer_text.lower()
        keywords = ("цен", "стоит", "стоим", "налич", "остат", "сколько", "артикул", "код")
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _guess_lookup_reason(customer_text: str) -> str:
        text = customer_text.lower()
        if "цена" in text or "стоит" in text:
            return "price"
        if "остат" in text or "в наличии" in text or "налич" in text:
            return "stock"
        if "сравн" in text:
            return "compare"
        return "product_info"

    def _log_lookup_result(self, *, stage: str, payload: dict[str, Any]) -> None:
        if not self.debug_lookup_logs:
            return
        logger.info("assistant_lookup_%s payload=%s", stage, json.dumps(payload, ensure_ascii=False))

    def _log_tool_turn(self, *, customer_text: str, turn) -> None:
        if not self.debug_lookup_logs:
            return
        logger.info(
            "assistant_tool_turn customer_text=%r tool_calls=%s text=%r",
            customer_text,
            [{"name": call.name, "arguments": call.arguments} for call in turn.tool_calls],
            turn.text,
        )

    @staticmethod
    def _build_programmatic_lookup_fallback(product_lookup_result: dict) -> str:
        status = product_lookup_result.get("status")
        exact = product_lookup_result.get("exact_matches", [])
        similar = product_lookup_result.get("similar_matches", [])
        query = product_lookup_result.get("query", "")

        if status in {"exact_found", "multiple_exact"} and exact:
            if len(exact) == 1:
                item = exact[0]
                return (
                    f"Артикул {item.get('article') or query} найден. "
                    f"Свободный остаток: {item.get('stock') or 'н/д'} {item.get('unit') or 'шт.'}. "
                    f"Розничная цена: {item.get('retail_price') or 'н/д'} руб."
                )
            lines = [f"Нашёл несколько позиций по запросу {query}:"]
            for index, item in enumerate(exact[:5], start=1):
                lines.append(
                    f"{index}. Код {item.get('code') or '-'} — остаток {item.get('stock') or 'н/д'} {item.get('unit') or 'шт.'}, "
                    f"цена {item.get('retail_price') or 'н/д'} ₽."
                )
            lines.append("Уточните, пожалуйста, какой код товара вам нужен.")
            return " ".join(lines)

        if status == "similar_found" and similar:
            preview = ", ".join((item.get("article") or "-") for item in similar[:5])
            return f"Точного совпадения не нашёл, но есть похожие варианты: {preview}. Уточните, пожалуйста, нужный артикул или код."

        return "Не нашёл точные данные по запросу. Проверьте артикул или код и пришлите ещё раз."

    @staticmethod
    def _resolve_handoff_text(handoff_mode: str) -> str:
        if handoff_mode == "demo":
            return TELEGRAM_DEMO_HANDOFF_TEXT
        return JIVO_HANDOFF_TEXT

    @staticmethod
    def _append_bot_message(
        session,
        *,
        external_chat_id: str,
        text: str,
        outbound_event_id: str | None,
        payload: dict | None = None,
    ) -> None:
        append_message(
            session,
            external_chat_id=external_chat_id,
            sender_role="bot",
            text=text,
            external_event_id=outbound_event_id,
            payload=payload or {},
        )
