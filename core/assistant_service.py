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
    "Добрый день! Подскажите, что нужно посмотреть?"
)

JIVO_HANDOFF_TEXT = "Передаю вопрос менеджеру. Он подключится к диалогу и поможет вам."

TELEGRAM_DEMO_HANDOFF_TEXT = JIVO_HANDOFF_TEXT

ARTICLE_REQUIRED_TEXT = (
    "Пришлите, пожалуйста, артикул или код товара. Тогда посмотрю цену и наличие."
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
        article_candidates = extract_article_candidates(customer_text)
        if self._is_explicit_manager_request(customer_text) and article_candidates:
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
                payload_source="backend_manager_prelookup",
                force_handoff_reason="client_requested_manager",
                handoff_mode=handoff_mode,
            )

        if self._is_explicit_manager_request(customer_text):
            return self._handoff_reply(
                session,
                external_chat_id=external_chat_id,
                handoff_mode=handoff_mode,
                outbound_event_id=outbound_event_id,
                reason="client_requested_manager",
                source="backend_rule",
            )

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

        if handoff_decision.should_handoff and handoff_decision.reason == "complex_technical_question" and article_candidates:
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
                payload_source="backend_complex_prelookup",
                force_handoff_reason="complex_technical_question",
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
        reply_text = self._sanitize_customer_reply(reply_text)

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
        requested_quantity = self._extract_requested_quantity(customer_text)
        stock_handoff_reason = self._get_stock_shortage_reason(product_lookup_result, requested_quantity)
        handoff_reason = force_handoff_reason or stock_handoff_reason
        backend_actions = {
            "search_products_called": True,
            "handoff_to_manager_called": bool(handoff_reason),
            "handoff_reason": handoff_reason,
        }

        turn = None
        if self.openai_service.enabled:
            fact_messages = build_product_facts_messages(
                transcript=transcript,
                customer_text=customer_text,
                product_lookup_result=product_lookup_result,
                backend_actions=backend_actions,
            )
            turn = self.openai_service.run_messages(messages=fact_messages)

        reply_text = (turn.text if turn else None) or self._build_programmatic_lookup_fallback(product_lookup_result)
        reply_text = self._sanitize_customer_reply(reply_text)

        if handoff_reason:
            self.handoff_service.register_handoff(session, external_chat_id, handoff_reason)
            reply_text = self._sanitize_customer_reply(self._ensure_handoff_text(reply_text, handoff_reason))

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
                "backend_actions": backend_actions,
                "handoff_reason": handoff_reason,
            },
        )
        return AssistantReply(text=reply_text, handoff_reason=handoff_reason)

    @staticmethod
    def _ensure_handoff_text(reply_text: str, handoff_reason: str) -> str:
        text_lower = reply_text.lower()
        if "переда" in text_lower and "менеджер" in text_lower:
            return reply_text

        if handoff_reason == "order_request":
            return f"{reply_text} Для оформления заказа передаю вопрос менеджеру."
        if handoff_reason == "requested_quantity_exceeds_stock":
            return f"{reply_text} Запрошенного количества может не хватить, передаю вопрос менеджеру для уточнения."
        if handoff_reason == "complex_technical_question":
            return (
                f"{reply_text} По текущей выгрузке могу сравнить только данные из базы: код, артикул, цену, "
                "остаток, единицу измерения, вес и объём. Технического описания отличий в базе нет. "
                "Передаю вопрос менеджеру. Он подключится к диалогу и поможет вам."
            )
        return f"{reply_text} Передаю вопрос менеджеру. Он подключится к диалогу и поможет вам."

    @staticmethod
    def _sanitize_customer_reply(reply_text: str) -> str:
        text = reply_text.replace("**", "").replace("__", "").replace("`", "")
        cleaned_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("- ", "* ")):
                stripped = stripped[2:].strip()
            cleaned_lines.append(stripped)
        text = "\n".join(line for line in cleaned_lines if line)
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()

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
        unique_exact: dict[str, dict] = {}
        unique_similar: dict[str, dict] = {}
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
            item_exact_keys = {
                match.get("code") or match.get("article") or str(index)
                for index, match in enumerate(item.get("exact_matches", []))
            }
            item_similar_keys = {
                match.get("code") or match.get("article") or str(index)
                for index, match in enumerate(item.get("similar_matches", []))
            }
            if item_exact_keys and item_exact_keys <= set(unique_exact):
                continue
            if not item_exact_keys and item_similar_keys and item_similar_keys <= set(unique_exact):
                continue
            per_query_results.append(item)
            for match in item.get("exact_matches", []):
                unique_exact[match.get("code") or match.get("article") or str(len(unique_exact))] = match
            for match in item.get("similar_matches", []):
                key = match.get("code") or match.get("article") or str(len(unique_similar))
                if key not in unique_exact:
                    unique_similar[key] = match
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

        exact_matches = list(unique_exact.values())
        similar_matches = [match for key, match in unique_similar.items() if key not in unique_exact]
        exact_count = len(exact_matches)
        similar_count = len(similar_matches)
        visible_query_results = per_query_results
        if exact_matches:
            visible_query_results = [item for item in per_query_results if item.get("status") != "similar_found"]
        summary = {
            "total_queries": len(visible_query_results),
            "total_exact_matches": exact_count,
            "total_similar_matches": 0 if exact_matches else similar_count,
            "has_errors": any(item.get("status") == "error" for item in visible_query_results),
        }

        return {
            "queries": queries,
            "reason": reason,
            **best,
            "exact_matches": exact_matches or best.get("exact_matches", []),
            "similar_matches": similar_matches if exact_matches else best.get("similar_matches", []),
            "exact_matches_count": exact_count if exact_matches else best.get("exact_matches_count", 0),
            "similar_matches_count": 0 if exact_matches else best.get("similar_matches_count", 0),
            "summary": summary,
            "results": visible_query_results,
            "per_query_results": visible_query_results,
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
        per_query_results = product_lookup_result.get("results") or product_lookup_result.get("per_query_results", [])

        if len(per_query_results) > 1:
            lines = ["Проверил."]
            for index, item in enumerate(per_query_results, start=1):
                item_status = item.get("status")
                item_query = item.get("query") or "запрос"
                item_exact = item.get("exact_matches", [])
                item_similar = item.get("similar_matches", [])
                if item_status in {"exact_found", "multiple_exact"} and item_exact:
                    if len(item_exact) == 1:
                        match = item_exact[0]
                        retail_price = AssistantService._format_number(match.get("retail_price"))
                        price_text = f", розничная цена {retail_price} руб" if retail_price else ", цена в текущей выгрузке не указана"
                        display_article = match.get("article") or item_query
                        lines.append(
                            f"По {display_article} остаток "
                            f"{AssistantService._format_quantity(match.get('stock'), match.get('unit'))}{price_text}."
                        )
                    else:
                        display_query = AssistantService._display_query_for_matches(item_query, item_exact)
                        lines.append(
                            f"По {display_query} нашёл несколько позиций. Они отличаются кодом и ценой, "
                            "поэтому уточните, пожалуйста, код товара с сайта или цену, которую видите."
                        )
                elif item_status == "similar_found" and item_similar:
                    variants = "; ".join(
                        f"{match.get('article') or '-'} — код {match.get('code') or '-'}"
                        for match in item_similar[:3]
                    )
                    lines.append(f"По {item_query} точного совпадения не нашёл. Похожие варианты: {variants}.")
                else:
                    lines.append(f"По {item_query} в текущей базе ничего не нашёл. Проверьте, пожалуйста, артикул или код.")
            return " ".join(lines)

        if status in {"exact_found", "multiple_exact"} and exact:
            if len(exact) == 1:
                item = exact[0]
                article = item.get("article") or query
                stock_text = AssistantService._format_quantity(item.get("stock"), item.get("unit"))
                retail_price = AssistantService._format_number(item.get("retail_price"))
                corporate_price = AssistantService._format_number(item.get("corporate_price"))
                parts = [AssistantService._finish_sentence(f"Да, нашёл {article}")]
                parts.append(f"Сейчас в наличии {stock_text}.")
                if retail_price:
                    parts.append(f"Розничная цена {retail_price} руб.")
                if corporate_price:
                    parts.append(f"Корпоративная цена {corporate_price} руб.")
                if not retail_price and not corporate_price:
                    parts.append("Цена в текущей выгрузке не указана.")
                return " ".join(parts)

            display_query = AssistantService._display_query_for_matches(query, exact)
            return (
                f"По {display_query} нашёл несколько позиций. Они отличаются кодом и ценой, поэтому чтобы не ошибиться, "
                "уточните, пожалуйста, код товара с сайта или цену, которую видите. После этого скажу точный остаток."
            )

        if status == "similar_found" and similar:
            variants = "; ".join(f"{item.get('article') or '-'} — код {item.get('code') or '-'}" for item in similar[:5])
            return (
                f"Точного совпадения по {query} не нашёл. Есть похожие варианты: {variants}. "
                "Если это не то, пришлите, пожалуйста, код товара с сайта."
            )

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
    def _format_quantity(value: Any, unit: Any) -> str:
        number = AssistantService._format_number(value) or "0"
        unit_text = str(unit or "шт").strip().rstrip(".") or "шт"
        return f"{number} {unit_text}"

    @staticmethod
    def _finish_sentence(text: str) -> str:
        stripped = text.rstrip()
        if stripped.endswith((".", "!", "?")):
            return stripped
        return f"{stripped}."

    @staticmethod
    def _display_query_for_matches(query: str, matches: list[dict]) -> str:
        articles = {str(item.get("article") or "").strip() for item in matches if item.get("article")}
        if len(articles) == 1:
            return next(iter(articles))
        return query

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
