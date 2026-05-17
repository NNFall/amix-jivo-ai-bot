from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import re
from typing import Any

from database.repositories import append_message, get_or_create_chat, get_or_create_customer, search_products_structured
from llm.openai_client import OpenAIService
from llm.prompts import build_llm_messages, build_product_facts_messages
from llm.tool_schemas import OPENAI_TOOLS
from products.article_utils import extract_article_candidates, normalize_article
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
        self.debug_llm_payloads = settings.assistant_debug_llm_payloads
        self.debug_llm_payloads_path = Path(settings.assistant_debug_llm_payloads_path)
        self.show_corporate_price = settings.show_corporate_price

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
        history_article_candidates = self._extract_history_article_candidates(transcript)
        if self._looks_like_price_refinement(customer_text, article_candidates) and history_article_candidates:
            article_candidates = history_article_candidates
        if self._is_explicit_manager_request(customer_text) and article_candidates:
            lookup_result = self._search_products_by_queries(
                session,
                queries=article_candidates,
                reason=self._guess_lookup_reason(customer_text),
                customer_text=customer_text,
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
                customer_text=customer_text,
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

        if (
            handoff_decision.should_handoff
            and handoff_decision.reason == "complex_technical_question"
            and not article_candidates
            and history_article_candidates
        ):
            article_candidates = history_article_candidates

        if handoff_decision.should_handoff and handoff_decision.reason == "complex_technical_question" and article_candidates:
            lookup_result = self._search_products_by_queries(
                session,
                queries=article_candidates,
                reason=self._guess_lookup_reason(customer_text),
                customer_text=customer_text,
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
                customer_text=customer_text,
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
        self._log_llm_debug_event(
            "llm_direct_request",
            {
                "external_chat_id": external_chat_id,
                "customer_text": customer_text,
                "transcript": transcript,
                "messages": messages,
                "tools": self._summarize_tools(OPENAI_TOOLS),
                "tool_choice": "auto",
            },
        )
        first_turn = self.openai_service.run_messages(messages=messages, tools=OPENAI_TOOLS, tool_choice="auto")
        self._log_llm_debug_event(
            "llm_direct_response",
            {
                "external_chat_id": external_chat_id,
                "customer_text": customer_text,
                "text": first_turn.text,
                "tool_calls": self._serialize_tool_calls(first_turn.tool_calls),
            },
        )
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
                customer_text=customer_text,
            )
            self._log_lookup_result(stage="tool_call", payload=lookup_result)
            self._log_llm_debug_event(
                "llm_tool_call_result",
                {
                    "external_chat_id": external_chat_id,
                    "customer_text": customer_text,
                    "tool_call": {
                        "name": call.name,
                        "arguments": call.arguments,
                        "call_id": call.call_id,
                    },
                    "lookup_result": lookup_result,
                },
            )
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
        product_lookup_result = self._apply_response_policy(product_lookup_result)
        followup_refinement = self._build_followup_refinement_context(customer_text, product_lookup_result)
        product_lookup_result = self._apply_followup_refinement(product_lookup_result, followup_refinement)
        stock_only_request = self._is_stock_only_request(customer_text)
        product_lookup_result = self._apply_stock_only_policy(product_lookup_result, stock_only_request)
        requested_quantity = self._extract_requested_quantity(customer_text)
        stock_handoff_reason = self._get_stock_shortage_reason(product_lookup_result, requested_quantity)
        corporate_price_handoff_reason = (
            "corporate_price_request"
            if self._is_corporate_price_request(customer_text) and not self.show_corporate_price
            else None
        )
        handoff_reason = stock_handoff_reason or force_handoff_reason or corporate_price_handoff_reason
        backend_actions = {
            "search_products_called": True,
            "handoff_to_manager_called": bool(handoff_reason),
            "handoff_reason": handoff_reason,
            "response_mode": self._resolve_response_mode(handoff_reason),
            "requested_quantity": requested_quantity,
            "show_corporate_price": self.show_corporate_price,
            "corporate_price_request": bool(corporate_price_handoff_reason),
            "queried_by_code": self._lookup_queried_by_code(customer_text, product_lookup_result),
            "stock_only_request": stock_only_request,
            "followup_refinement": followup_refinement,
        }

        turn = None
        if self.openai_service.enabled:
            fact_messages = build_product_facts_messages(
                transcript=transcript,
                customer_text=customer_text,
                product_lookup_result=product_lookup_result,
                backend_actions=backend_actions,
            )
            self._log_llm_debug_event(
                "product_facts_request",
                {
                    "external_chat_id": external_chat_id,
                    "customer_text": customer_text,
                    "transcript": transcript,
                    "product_lookup_result": product_lookup_result,
                    "backend_actions": backend_actions,
                    "messages": fact_messages,
                    "note": (
                        "messages is the exact role-based payload sent to the LLM. "
                        "The dialog history is currently packed into a user message as transcript text."
                    ),
                },
            )
            turn = self.openai_service.run_messages(messages=fact_messages)
            self._log_llm_debug_event(
                "product_facts_response",
                {
                    "external_chat_id": external_chat_id,
                    "customer_text": customer_text,
                    "text": turn.text,
                    "tool_calls": self._serialize_tool_calls(turn.tool_calls),
                },
            )

        reply_text = (turn.text if turn else None) or self._build_programmatic_lookup_fallback(
            product_lookup_result,
            customer_text=customer_text,
            backend_actions=backend_actions,
        )
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

    def _apply_response_policy(self, product_lookup_result: dict) -> dict:
        payload = deepcopy(product_lookup_result)
        if self.show_corporate_price:
            return payload

        for container in self._iter_lookup_result_containers(payload):
            for key in ("exact_matches", "similar_matches"):
                for match in container.get(key, []):
                    match["corporate_price"] = None
                    match["corporate_price_display"] = None
        return payload

    @staticmethod
    def _iter_lookup_result_containers(product_lookup_result: dict) -> list[dict]:
        containers = [product_lookup_result]
        containers.extend(product_lookup_result.get("results") or [])
        containers.extend(product_lookup_result.get("per_query_results") or [])
        return [item for item in containers if isinstance(item, dict)]

    @staticmethod
    def _apply_stock_only_policy(product_lookup_result: dict, stock_only_request: bool) -> dict:
        exact = product_lookup_result.get("exact_matches") or []
        if not stock_only_request or len(exact) != 1:
            return product_lookup_result

        payload = deepcopy(product_lookup_result)
        for container in AssistantService._iter_lookup_result_containers(payload):
            for key in ("exact_matches", "similar_matches"):
                for match in container.get(key, []):
                    match["retail_price"] = None
                    match["retail_price_display"] = None
                    match["corporate_price"] = None
                    match["corporate_price_display"] = None
        return payload

    @staticmethod
    def _apply_followup_refinement(product_lookup_result: dict, refinement_context: dict) -> dict:
        if not refinement_context.get("is_likely_followup_refinement"):
            return product_lookup_result

        matches = refinement_context.get("matched_exact_matches") or []
        if len(matches) != 1:
            return product_lookup_result

        selected = matches[0]
        payload = deepcopy(product_lookup_result)
        payload["status"] = "exact_found"
        payload["exact_matches"] = [selected]
        payload["similar_matches"] = []
        payload["exact_matches_count"] = 1
        payload["similar_matches_count"] = 0
        payload["resolved_followup_refinement"] = {
            "matched_by": refinement_context.get("matched_by"),
            "value": refinement_context.get("matched_value"),
            "code": selected.get("code"),
            "article": selected.get("article"),
        }

        for container in AssistantService._iter_lookup_result_containers(payload):
            container_exact = container.get("exact_matches") or []
            if not any(AssistantService._same_product(match, selected) for match in container_exact):
                continue
            container["status"] = "exact_found"
            container["exact_matches"] = [selected]
            container["similar_matches"] = []
            container["exact_matches_count"] = 1
            container["similar_matches_count"] = 0

        payload["summary"] = {
            "total_queries": 1,
            "total_exact_matches": 1,
            "total_similar_matches": 0,
            "has_errors": False,
        }
        return payload

    @staticmethod
    def _resolve_response_mode(handoff_reason: str | None) -> str | None:
        if handoff_reason == "requested_quantity_exceeds_stock":
            return "stock_shortage_handoff"
        if handoff_reason == "order_request":
            return "order_handoff"
        if handoff_reason == "corporate_price_request":
            return "corporate_price_handoff"
        if handoff_reason:
            return "handoff"
        return None

    @staticmethod
    def _is_corporate_price_request(customer_text: str) -> bool:
        text = customer_text.lower()
        keywords = ("корпоратив", "опт", "оптов", "юрлиц", "юр. лиц", "скидк")
        return any(keyword in text for keyword in keywords) or bool(re.search(r"\bкорп\b", text))

    @staticmethod
    def _lookup_queried_by_code(customer_text: str, product_lookup_result: dict) -> bool:
        text = customer_text.lower()
        if "код" in text:
            return True

        query_values = [
            product_lookup_result.get("query"),
            product_lookup_result.get("display_query"),
        ]
        query_values.extend(product_lookup_result.get("queries") or [])
        normalized_queries = {normalize_article(str(value)) for value in query_values if value}
        exact = product_lookup_result.get("exact_matches") or []
        for match in exact:
            code = normalize_article(str(match.get("code") or ""))
            if code and code in normalized_queries:
                return True
        return False

    @staticmethod
    def _build_followup_refinement_context(customer_text: str, product_lookup_result: dict) -> dict:
        exact = product_lookup_result.get("exact_matches") or []
        if len(exact) < 2:
            return {}

        text = customer_text.lower()
        values = re.findall(r"(?<!\d)(\d+(?:[,.]\d{1,2})?)(?!\d)", text)
        has_refinement_word = any(
            keyword in text
            for keyword in ("цен", "руб", "код", "та что", "тот что", "по ")
        ) or any(keyword in text for keyword in ("стоит", "стоимость", "которая", "который", "за "))
        if not values or not has_refinement_word:
            return {}

        if "код" in text:
            refinement_type = "code"
        elif "цен" in text or "руб" in text or "стоит" in text or "стоимость" in text:
            refinement_type = "price"
        else:
            refinement_type = "number"

        matched = AssistantService._match_refinement_to_exact_matches(values, refinement_type, exact)

        return {
            "is_likely_followup_refinement": True,
            "refinement_type": refinement_type,
            "values": values[:3],
            "matched_exact_count": len(matched),
            "matched_exact_matches": matched[:2],
            "matched_by": refinement_type if len(matched) == 1 else None,
            "matched_value": values[0] if len(matched) == 1 and values else None,
            "instruction": (
                "Текущее сообщение похоже на уточнение предыдущего выбора. "
                "Сначала сопоставь values с кодом, розничной ценой или корпоративной ценой "
                "в exact_matches. Если ровно одна позиция подходит, ответь по ней и не проси "
                "код или цену повторно."
            ),
        }

    @staticmethod
    def _match_refinement_to_exact_matches(values: list[str], refinement_type: str, exact: list[dict]) -> list[dict]:
        if not values:
            return []

        normalized_values = {AssistantService._normalize_refinement_value(value) for value in values}
        result: list[dict] = []
        for match in exact:
            candidates = [match.get("code")]
            if refinement_type in {"price", "number"}:
                candidates.extend(
                    [
                        match.get("retail_price"),
                        match.get("retail_price_display"),
                        match.get("corporate_price"),
                        match.get("corporate_price_display"),
                    ]
                )
            if any(AssistantService._normalize_refinement_value(candidate) in normalized_values for candidate in candidates if candidate):
                result.append(match)
        return result

    @staticmethod
    def _normalize_refinement_value(value: Any) -> str:
        text = str(value).lower().replace(",", ".")
        number_match = re.search(r"\d+(?:\.\d+)?", text)
        if not number_match:
            return normalize_article(text)
        number = number_match.group(0)
        try:
            numeric = float(number)
        except ValueError:
            return number
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _same_product(left: dict, right: dict) -> bool:
        return str(left.get("code") or "") == str(right.get("code") or "") and str(left.get("article") or "") == str(right.get("article") or "")

    @staticmethod
    def _ensure_handoff_text(reply_text: str, handoff_reason: str) -> str:
        text_lower = reply_text.lower()
        if handoff_reason == "requested_quantity_exceeds_stock":
            cleaned = re.sub(
                r"Передаю заказ менеджеру\.[^.]*поможет оформить\.?",
                "Передаю вопрос менеджеру. Он подключится к диалогу и уточнит возможность заказа или замены.",
                reply_text,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(
                r"поможет оформить",
                "уточнит возможность заказа или замены",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(
                r"поможет с оформлением",
                "уточнит возможность заказа или замены",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned_lower = cleaned.lower()
            if "уточнит возможность" in cleaned_lower or "подбер" in cleaned_lower:
                return cleaned
            return (
                f"{cleaned} Передаю вопрос менеджеру. "
                "Он подключится к диалогу и уточнит возможность заказа или замены."
            )

        if "переда" in text_lower and "менеджер" in text_lower:
            return reply_text

        if handoff_reason == "order_request":
            return f"{reply_text} Передаю заказ менеджеру. Он подключится к диалогу и поможет оформить."
        if handoff_reason == "corporate_price_request":
            return f"{reply_text} Передаю вопрос менеджеру. Он подключится к диалогу и уточнит условия по цене."
        if handoff_reason == "complex_technical_question":
            return (
                f"{reply_text} По текущим данным могу сравнить только данные из базы: код, артикул, цену, "
                "остаток, единицу измерения, вес и объём. Технического описания отличий в базе нет. "
                "Передаю вопрос менеджеру. Он подключится к диалогу и поможет вам."
            )
        return f"{reply_text} Передаю вопрос менеджеру. Он подключится к диалогу и поможет вам."

    @staticmethod
    def _sanitize_customer_reply(reply_text: str) -> str:
        text = reply_text.replace("**", "").replace("__", "").replace("`", "")
        text = re.sub(r"\b[Вв] текущей выгрузке\b", "в текущих данных", text)
        text = re.sub(r"\b[Пп]о текущей выгрузке\b", "по текущим данным", text)
        text = re.sub(r"\b[Тт]екущей выгрузки\b", "текущих данных", text)
        text = re.sub(r"\b[Тт]екущая выгрузка\b", "текущие данные", text)
        text = re.sub(r"\b[Вв]ыгрузке\b", "текущих данных", text)
        text = re.sub(r"\b[Вв]ыгрузка\b", "текущие данные", text)
        text = re.sub(r"\b[Оо]н свяжется с вами\b", "он подключится к диалогу", text)
        text = re.sub(r"\b[Мм]енеджер свяжется с вами\b", "менеджер подключится к диалогу", text)
        text = re.sub(r"\b[Сс]вяжется с вами\b", "подключится к диалогу", text)
        text = re.sub(r"\b([Кк]од(?:у|ом)?)(\d+)\b", r"\1 \2", text)
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

    def _search_products_by_queries(
        self,
        session,
        *,
        queries: list[str],
        reason: str,
        customer_text: str | None = None,
    ) -> dict:
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
            display_query = self._resolve_display_query(query, customer_text)
            search_query = display_query or query
            item = search_products_structured(session, query=search_query, search_type="auto")
            item["raw_backend_query"] = query
            item["display_query"] = display_query
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
                "display_query": "",
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
            "display_queries": [item.get("display_query") or item.get("query") for item in visible_query_results],
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
        handoff_text = self._resolve_handoff_text(handoff_mode, reason)
        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=self._sanitize_customer_reply(handoff_text),
            outbound_event_id=outbound_event_id,
            payload={"source": source, "handoff_reason": reason},
        )
        return AssistantReply(text=self._sanitize_customer_reply(handoff_text), handoff_reason=reason)

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
    def _is_stock_only_request(customer_text: str) -> bool:
        text = customer_text.lower()
        has_stock_intent = any(keyword in text for keyword in ("налич", "остат", "есть"))
        has_price_intent = any(keyword in text for keyword in ("цен", "стоит", "стоим", "руб", "корп", "опт"))
        has_order_intent = any(keyword in text for keyword in ("заказ", "купить", "оформ"))
        return has_stock_intent and not has_price_intent and not has_order_intent

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

    @staticmethod
    def _extract_history_article_candidates(transcript: str) -> list[str]:
        candidates = extract_article_candidates(transcript or "")
        result: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            result.append(candidate)
        return result[:5]

    @staticmethod
    def _looks_like_price_refinement(customer_text: str, article_candidates: list[str]) -> bool:
        text = customer_text.lower()
        if "код" in text:
            return False
        stripped = re.sub(r"\s+", " ", text).strip()
        is_short_number = bool(re.fullmatch(r"\d+(?:[,.]\d{1,2})?", stripped))
        if not (
            "цен" in text
            or "руб" in text
            or "стоит" in text
            or "стоимость" in text
            or "та что" in text
            or "которая" in text
            or "который" in text
            or "по " in text
            or "за " in text
            or is_short_number
        ):
            return False
        return bool(article_candidates) and all(candidate.isdigit() for candidate in article_candidates)

    def _log_lookup_result(self, *, stage: str, payload: dict[str, Any]) -> None:
        if self.debug_lookup_logs:
            logger.info("assistant_lookup_%s payload=%s", stage, json.dumps(payload, ensure_ascii=False))

    def _log_llm_debug_event(self, stage: str, payload: dict[str, Any]) -> None:
        if not self.debug_llm_payloads:
            return

        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "stage": stage,
            "provider": self.openai_service.provider,
            "model": (
                self.openai_service.kie_chat_model_path
                if self.openai_service.provider == "kie"
                else self.openai_service.model
            ),
            "payload": payload,
        }

        try:
            self.debug_llm_payloads_path.parent.mkdir(parents=True, exist_ok=True)
            with self.debug_llm_payloads_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(event, ensure_ascii=False, default=str))
                file.write("\n")
        except Exception:  # pragma: no cover - debug logging must not break replies
            logger.exception("Failed to write LLM debug payload")

    @staticmethod
    def _serialize_tool_calls(tool_calls: list) -> list[dict[str, Any]]:
        return [
            {
                "name": call.name,
                "arguments": call.arguments,
                "call_id": call.call_id,
            }
            for call in tool_calls
        ]

    @staticmethod
    def _summarize_tools(tools: list[dict]) -> list[dict[str, Any]]:
        result = []
        for tool in tools:
            function = tool.get("function") or {}
            result.append(
                {
                    "type": tool.get("type"),
                    "name": function.get("name"),
                    "description": function.get("description"),
                    "parameters": function.get("parameters"),
                }
            )
        return result

    def _log_tool_turn(self, *, customer_text: str, turn) -> None:
        if self.debug_lookup_logs:
            logger.info(
                "assistant_tool_turn customer_text=%r tool_calls=%s text=%r",
                customer_text,
                [{"name": call.name, "arguments": call.arguments} for call in turn.tool_calls],
                turn.text,
            )

    @staticmethod
    def _build_programmatic_lookup_fallback(
        product_lookup_result: dict,
        *,
        customer_text: str = "",
        backend_actions: dict | None = None,
    ) -> str:
        backend_actions = backend_actions or {}
        status = product_lookup_result.get("status")
        exact = product_lookup_result.get("exact_matches", [])
        similar = product_lookup_result.get("similar_matches", [])
        query = product_lookup_result.get("display_query") or product_lookup_result.get("query", "")
        per_query_results = product_lookup_result.get("results") or product_lookup_result.get("per_query_results", [])
        show_corporate_price = backend_actions.get("show_corporate_price", True)

        if len(per_query_results) > 1:
            lines = ["Проверил."]
            for index, item in enumerate(per_query_results, start=1):
                item_status = item.get("status")
                item_query = item.get("display_query") or item.get("query") or "запрос"
                item_exact = item.get("exact_matches", [])
                item_similar = item.get("similar_matches", [])
                if item_status in {"exact_found", "multiple_exact"} and item_exact:
                    if len(item_exact) == 1:
                        match = item_exact[0]
                        retail_price = AssistantService._format_price_text(match.get("retail_price_display"), match.get("retail_price"))
                        price_text = f", розничная цена {retail_price}" if retail_price else ", цена в текущих данных не указана"
                        display_article = match.get("article") or item_query
                        prefix = f"По {display_article} остаток "
                        if AssistantService._lookup_item_queried_by_code(customer_text, item, match):
                            prefix = f"По коду {match.get('code')} нашёл артикул {display_article}, остаток "
                        lines.append(
                            prefix +
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
                retail_price = AssistantService._format_price_text(item.get("retail_price_display"), item.get("retail_price"))
                corporate_price = (
                    AssistantService._format_price_text(item.get("corporate_price_display"), item.get("corporate_price"))
                    if show_corporate_price
                    else None
                )
                if AssistantService._lookup_item_queried_by_code(customer_text, product_lookup_result, item):
                    code = item.get("code") or query
                    parts = [AssistantService._finish_sentence(f"По коду {code} нашёл артикул {article}")]
                else:
                    parts = [AssistantService._finish_sentence(f"Да, нашёл {article}")]
                parts.append(f"Сейчас в наличии {stock_text}.")
                if retail_price:
                    parts.append(f"Розничная цена {retail_price}.")
                if corporate_price:
                    parts.append(f"Корпоративная цена {corporate_price}.")
                if not retail_price and not corporate_price:
                    parts.append("Цена в текущих данных не указана.")
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
    def _format_price_text(display_value: Any, raw_value: Any) -> str | None:
        if display_value:
            return str(display_value).strip().rstrip(".")
        number = AssistantService._format_number(raw_value)
        if not number:
            return None
        return f"{number} руб"

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
    def _resolve_display_query(query: str, customer_text: str | None) -> str:
        if not customer_text:
            return query

        query_normalized = normalize_article(query)
        if not query_normalized:
            return query

        tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-_/\.]*", customer_text)
        max_window = min(5, len(tokens))
        for size in range(max_window, 0, -1):
            for start in range(0, len(tokens) - size + 1):
                phrase = " ".join(tokens[start : start + size]).strip()
                if normalize_article(phrase) == query_normalized:
                    return phrase
        return query

    @staticmethod
    def _lookup_item_queried_by_code(customer_text: str, lookup_item: dict, match: dict) -> bool:
        if "код" in customer_text.lower():
            return True

        code = normalize_article(str(match.get("code") or ""))
        if not code:
            return False

        values = [
            lookup_item.get("query"),
            lookup_item.get("display_query"),
        ]
        values.extend(lookup_item.get("queries") or [])
        return code in {normalize_article(str(value)) for value in values if value}

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
    def _resolve_handoff_text(handoff_mode: str, reason: str | None = None) -> str:
        if reason == "complex_technical_question":
            return (
                "Для точного подбора нужны параметры: размеры, нагрузка и тип установки. "
                "Передаю вопрос менеджеру. Он подключится к диалогу и поможет подобрать вариант."
            )
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
