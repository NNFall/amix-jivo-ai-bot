from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any

from database.repositories import append_message, get_or_create_chat, get_or_create_customer, search_products_structured
from llm.openai_client import OpenAIService
from llm.prompts import build_llm_messages, build_product_facts_messages
from llm.tool_schemas import OPENAI_TOOLS
from products.article_utils import extract_article_candidates
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
        customer = get_or_create_customer(session, external_client_id=external_client_id, name=customer_name)
        chat = get_or_create_chat(session, external_chat_id, customer.id)

        append_message(
            session,
            external_chat_id=chat.external_chat_id,
            sender_role="client",
            text=customer_text,
            external_event_id=inbound_event_id,
            payload=payload or {},
        )

        transcript = self.dialog_service.get_transcript(session, chat.external_chat_id)
        return self._handle_message(
            session,
            external_chat_id=chat.external_chat_id,
            customer_text=customer_text,
            transcript=transcript,
            outbound_event_id=outbound_event_id,
            handoff_mode=handoff_mode,
        )

    def _handle_message(
        self,
        session,
        *,
        external_chat_id: str,
        customer_text: str,
        transcript: str,
        outbound_event_id: str | None,
        handoff_mode: str,
    ) -> AssistantReply:
        if self._is_explicit_manager_request(customer_text):
            return self._handoff_reply(
                session,
                external_chat_id=external_chat_id,
                handoff_mode=handoff_mode,
                outbound_event_id=outbound_event_id,
                reason="client_requested_manager",
                source="backend_rule",
            )

        article_candidates = extract_article_candidates(customer_text)
        handoff_decision = self.handoff_service.evaluate(customer_text)

        if handoff_decision.should_handoff and handoff_decision.reason == "order_request" and article_candidates:
            lookup_result = self._search_products_by_queries(
                session,
                queries=article_candidates,
                reason=self._guess_lookup_reason(customer_text),
            )
            return self._reply_from_product_result(
                session,
                external_chat_id=external_chat_id,
                customer_text=customer_text,
                transcript=transcript,
                product_lookup_result=lookup_result,
                outbound_event_id=outbound_event_id,
                payload_source="backend_order_prelookup",
                force_handoff_reason="order_request",
                handoff_mode=handoff_mode,
            )

        if handoff_decision.should_handoff and handoff_decision.reason:
            return self._handoff_reply(
                session,
                external_chat_id=external_chat_id,
                handoff_mode=handoff_mode,
                outbound_event_id=outbound_event_id,
                reason=handoff_decision.reason,
                source="backend_handoff_rule",
            )

        if article_candidates:
            lookup_result = self._search_products_by_queries(
                session,
                queries=article_candidates,
                reason=self._guess_lookup_reason(customer_text),
            )
            self._log_lookup_result(stage="prelookup", payload=lookup_result)
            return self._reply_from_product_result(
                session,
                external_chat_id=external_chat_id,
                customer_text=customer_text,
                transcript=transcript,
                product_lookup_result=lookup_result,
                outbound_event_id=outbound_event_id,
                payload_source="backend_prelookup",
                handoff_mode=handoff_mode,
            )

        if not self.openai_service.enabled:
            return self._fallback_without_llm(
                session,
                external_chat_id=external_chat_id,
                customer_text=customer_text,
                outbound_event_id=outbound_event_id,
            )

        messages = build_llm_messages(transcript=transcript, customer_text=customer_text, product_lookup_result=None)
        first_turn = self.openai_service.run_messages(messages=messages, tools=OPENAI_TOOLS, tool_choice="auto")
        self._log_tool_turn(customer_text=customer_text, turn=first_turn)

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

        reply_text = first_turn.text
        if not reply_text:
            reply_text = ARTICLE_REQUIRED_TEXT if self._is_price_stock_request(customer_text) else SAFE_FALLBACK_TEXT

        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=reply_text,
            outbound_event_id=outbound_event_id,
            payload={"source": "llm_direct" if first_turn.text else "fallback"},
        )
        return AssistantReply(text=reply_text)

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

            lookup_result = self._search_products_by_queries(
                session,
                queries=queries,
                reason=str(call.arguments.get("reason") or "unknown"),
            )
            self._log_lookup_result(stage="tool_call", payload=lookup_result)
            return self._reply_from_product_result(
                session,
                external_chat_id=external_chat_id,
                customer_text=customer_text,
                transcript=transcript,
                product_lookup_result=lookup_result,
                outbound_event_id=outbound_event_id,
                payload_source="llm_tool_search",
                handoff_mode=handoff_mode,
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
        force_handoff_reason: str | None = None,
        handoff_mode: str = "jivo",
    ) -> AssistantReply:
        turn = None
        if self.openai_service.enabled:
            fact_messages = build_product_facts_messages(
                transcript=transcript,
                customer_text=customer_text,
                product_lookup_result=product_lookup_result,
            )
            turn = self.openai_service.run_messages(messages=fact_messages)

        reply_text = (turn.text if turn else None) or self._build_programmatic_lookup_fallback(product_lookup_result)
        requested_quantity = self._extract_requested_quantity(customer_text)
        stock_handoff_reason = self._get_stock_shortage_reason(product_lookup_result, requested_quantity)
        handoff_reason = force_handoff_reason or stock_handoff_reason

        if handoff_reason:
            self.handoff_service.register_handoff(session, external_chat_id, handoff_reason)
            if handoff_reason == "order_request":
                reply_text = f"{reply_text} Для оформления заказа передаю вопрос менеджеру."
            elif handoff_reason == "requested_quantity_exceeds_stock":
                reply_text = f"{reply_text} Запрошенного количества может не хватить, лучше передам вопрос менеджеру для уточнения."

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
                "handoff_reason": handoff_reason,
            },
        )
        return AssistantReply(text=reply_text, handoff_reason=handoff_reason)

    def _fallback_without_llm(
        self,
        session,
        *,
        external_chat_id: str,
        customer_text: str,
        outbound_event_id: str | None,
    ) -> AssistantReply:
        reply_text = ARTICLE_REQUIRED_TEXT if self._is_price_stock_request(customer_text) else SAFE_FALLBACK_TEXT
        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=reply_text,
            outbound_event_id=outbound_event_id,
            payload={"source": "fallback_without_llm"},
        )
        return AssistantReply(text=reply_text)

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
            if best is None or priority.get(item["status"], 99) < priority.get(best["status"], 99):
                best = item

        if best is None:
            best = {
                "query": "",
                "query_normalized": "",
                "search_type": "auto",
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
        if "цен" in text or "стоит" in text:
            return "price"
        if "остат" in text or "в наличии" in text or "налич" in text:
            return "stock"
        if "сравн" in text:
            return "compare"
        return "product_info"

    def _log_lookup_result(self, *, stage: str, payload: dict[str, Any]) -> None:
        if self.debug_lookup_logs:
            logger.info("assistant_lookup_%s payload=%s", stage, json.dumps(payload, ensure_ascii=False))

    def _log_tool_turn(self, *, customer_text: str, turn) -> None:
        if self.debug_lookup_logs:
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
        per_query_results = product_lookup_result.get("per_query_results", [])

        successful_queries = [
            item for item in per_query_results if item.get("status") in {"exact_found", "multiple_exact"}
        ]
        if len(successful_queries) > 1:
            lines = ["Проверил:"]
            for index, item in enumerate(successful_queries, start=1):
                match = item["exact_matches"][0]
                lines.append(
                    f"{index}. {match.get('article') or item.get('query')} — код {match.get('code') or '-'}, "
                    f"остаток {AssistantService._format_number(match.get('stock'))} {match.get('unit') or 'шт.'}, "
                    f"розничная цена {AssistantService._format_number(match.get('retail_price')) or 'н/д'} руб."
                )
            return " ".join(lines)

        if status in {"exact_found", "multiple_exact"} and exact:
            if len(exact) == 1:
                item = exact[0]
                parts = [
                    f"Артикул {item.get('article') or query} найден.",
                    f"Код: {item.get('code') or 'н/д'}.",
                    f"Свободный остаток: {AssistantService._format_number(item.get('stock'))} {item.get('unit') or 'шт.'}.",
                ]
                retail_price = AssistantService._format_number(item.get("retail_price"))
                corporate_price = AssistantService._format_number(item.get("corporate_price"))
                if retail_price:
                    parts.append(f"Розничная цена: {retail_price} руб.")
                if corporate_price:
                    parts.append(f"Корпоративная цена: {corporate_price} руб.")
                if not retail_price and not corporate_price:
                    parts.append("Цена в текущей выгрузке не указана.")
                return " ".join(parts)

            lines = [f"Нашёл несколько позиций по запросу {query}:"]
            for index, item in enumerate(exact[:5], start=1):
                lines.append(
                    f"{index}. Код {item.get('code') or '-'} — остаток {AssistantService._format_number(item.get('stock'))} "
                    f"{item.get('unit') or 'шт.'}, цена {AssistantService._format_number(item.get('retail_price')) or 'н/д'} руб."
                )
            lines.append("Уточните, пожалуйста, какой код товара вам нужен.")
            return " ".join(lines)

        if status == "similar_found" and similar:
            lines = [f"Точного совпадения по {query} не нашёл, но есть похожие варианты:"]
            for index, item in enumerate(similar[:5], start=1):
                lines.append(
                    f"{index}. {item.get('article') or '-'} — код {item.get('code') or '-'}, "
                    f"остаток {AssistantService._format_number(item.get('stock'))} {item.get('unit') or 'шт.'}, "
                    f"цена {AssistantService._format_number(item.get('retail_price')) or 'н/д'} руб."
                )
            lines.append("Уточните, пожалуйста, какой вариант нужен.")
            return " ".join(lines)

        return f"По запросу {query} в текущей базе ничего не нашёл. Проверьте, пожалуйста, артикул или код."

    @staticmethod
    def _format_number(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        if "." not in text:
            return text
        return text.rstrip("0").rstrip(".")

    @staticmethod
    def _extract_requested_quantity(customer_text: str) -> int | None:
        match = re.search(r"(?<![\w.])(\d+)\s*(?:шт|штук|штуки|штуку)\b", customer_text.lower())
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _get_stock_shortage_reason(product_lookup_result: dict, requested_quantity: int | None) -> str | None:
        if requested_quantity is None:
            return None
        exact = product_lookup_result.get("exact_matches", [])
        if len(exact) != 1:
            return None
        stock_raw = exact[0].get("stock")
        if stock_raw is None:
            return None
        try:
            stock_value = float(stock_raw)
        except (TypeError, ValueError):
            return None
        if stock_value < requested_quantity:
            return "requested_quantity_exceeds_stock"
        return None

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
