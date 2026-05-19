from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import re
from typing import Any

from database.repositories import (
    append_message,
    get_chat_by_external_id,
    get_or_create_chat,
    get_or_create_customer,
    list_recent_messages,
    search_products_structured,
)
from llm.openai_client import OpenAIService, ToolCall
from llm.prompts import build_company_faq_messages, build_llm_messages, build_product_facts_messages
from llm.tool_schemas import OPENAI_TOOLS
from products.article_utils import extract_article_candidates, normalize_article
from settings import get_settings

from .dialog_service import DialogService
from .handoff_service import HandoffService


logger = logging.getLogger(__name__)


SAFE_FALLBACK_TEXT = "Подскажите, что нужно посмотреть?"

PROVIDER_DELAY_TEXT = (
    "Сейчас автоматическая проверка задерживается. Попробуйте, пожалуйста, ещё раз чуть позже "
    "или позовите менеджера."
)

JIVO_HANDOFF_TEXT = "Передаю вопрос менеджеру. Он подключится к диалогу и поможет вам."

TELEGRAM_DEMO_HANDOFF_TEXT = JIVO_HANDOFF_TEXT
HANDOFF_ALREADY_REQUESTED_TEXT = "Менеджер уже вызван, он подключится к диалогу."

ARTICLE_REQUIRED_TEXT = (
    "Пришлите, пожалуйста, артикул или код товара. Тогда посмотрю цену и наличие."
)


@dataclass(slots=True)
class AssistantReply:
    text: str
    handoff_reason: str | None = None
    superseded: bool = False


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
        self.deterministic_company_faq_enabled = settings.assistant_deterministic_company_faq_enabled

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
        is_turn_current=None,
    ) -> AssistantReply:
        chat_external_id = self.record_client_message(
            session,
            external_chat_id=external_chat_id,
            external_client_id=external_client_id,
            customer_name=customer_name,
            customer_text=customer_text,
            inbound_event_id=inbound_event_id,
            payload=payload,
        )
        return self.handle_pending_client_messages(
            session,
            external_chat_id=chat_external_id,
            outbound_event_id=outbound_event_id,
            handoff_mode=handoff_mode,
            is_turn_current=is_turn_current,
        )

    def record_client_message(
        self,
        session,
        *,
        external_chat_id: str,
        external_client_id: str,
        customer_name: str | None,
        customer_text: str,
        inbound_event_id: str | None,
        payload: dict | None = None,
    ) -> str:
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
        return chat.external_chat_id

    def handle_pending_client_messages(
        self,
        session,
        *,
        external_chat_id: str,
        outbound_event_id: str | None,
        handoff_mode: str = "jivo",
        is_turn_current=None,
    ) -> AssistantReply:
        if self._turn_is_stale(is_turn_current):
            return self._superseded_reply()

        chat = get_chat_by_external_id(session, external_chat_id)
        if chat is None:
            return self._superseded_reply()
        if chat.status == "handoff_requested":
            return self._handoff_already_requested_reply(
                session,
                external_chat_id=chat.external_chat_id,
                outbound_event_id=outbound_event_id,
            )

        pending_messages = self._collect_pending_client_messages(
            list_recent_messages(session, chat.external_chat_id, limit=self.dialog_service.history_limit)
        )
        if not pending_messages:
            return self._superseded_reply()

        customer_text = "\n".join(message.text.strip() for message in pending_messages if message.text.strip()).strip()
        if not customer_text:
            return self._superseded_reply()

        transcript = self.dialog_service.get_transcript(session, chat.external_chat_id)
        return self._handle_message(
            session,
            external_chat_id=chat.external_chat_id,
            customer_text=customer_text,
            transcript=transcript,
            outbound_event_id=outbound_event_id,
            handoff_mode=handoff_mode,
            is_turn_current=is_turn_current,
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
        is_turn_current=None,
    ) -> AssistantReply:
        if self._turn_is_stale(is_turn_current):
            return self._superseded_reply()

        recent_messages = list_recent_messages(session, external_chat_id, limit=self.dialog_service.history_limit)
        article_candidates = self._sort_queries_by_text_order(extract_article_candidates(customer_text), customer_text)
        history_article_candidates = self._extract_recent_lookup_article_candidates(recent_messages)
        pending_lookup = self._find_latest_pending_product_lookup(recent_messages)
        if self._looks_like_price_refinement(customer_text, article_candidates):
            if pending_lookup:
                pending_refinement = self._build_followup_refinement_context(customer_text, pending_lookup)
                if pending_refinement.get("matched_exact_count") != 1:
                    pending_query = self._resolve_pending_lookup_query(pending_lookup)
                    if pending_query:
                        pending_lookup = self._search_products_by_queries(
                            session,
                            queries=[pending_query],
                            reason="price",
                            customer_text=customer_text,
                        )
                return self._reply_from_product_result(
                    session,
                    external_chat_id=external_chat_id,
                    customer_text=customer_text,
                    transcript=transcript,
                    product_lookup_result=pending_lookup,
                    outbound_event_id=outbound_event_id,
                    payload_source="backend_context_refinement",
                    handoff_mode=handoff_mode,
                    is_turn_current=is_turn_current,
                )
        contextual_followup_queries = self._resolve_contextual_product_followup_queries(customer_text, recent_messages)
        if contextual_followup_queries:
            lookup_result = self._search_products_by_queries(
                session,
                queries=contextual_followup_queries,
                reason=self._guess_lookup_reason(customer_text),
                customer_text=customer_text,
            )
            self._log_lookup_result(stage="context_followup", payload=lookup_result)
            return self._reply_from_product_result(
                session,
                external_chat_id=external_chat_id,
                customer_text=customer_text,
                transcript=transcript,
                product_lookup_result=lookup_result,
                outbound_event_id=outbound_event_id,
                payload_source="backend_context_followup",
                handoff_mode=handoff_mode,
                is_turn_current=is_turn_current,
            )
        if (
            not article_candidates
            and history_article_candidates
            and self._looks_like_explicit_history_article_followup(customer_text)
        ):
            article_candidates = self._select_history_candidates_for_followup(customer_text, history_article_candidates)
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
                is_turn_current=is_turn_current,
            )

        if self._is_explicit_manager_request(customer_text):
            return self._handoff_reply(
                session,
                external_chat_id=external_chat_id,
                handoff_mode=handoff_mode,
                outbound_event_id=outbound_event_id,
                reason="client_requested_manager",
                source="backend_rule",
                is_turn_current=is_turn_current,
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
                is_turn_current=is_turn_current,
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
                is_turn_current=is_turn_current,
            )

        if handoff_decision.should_handoff and handoff_decision.reason:
            return self._handoff_reply(
                session,
                external_chat_id=external_chat_id,
                handoff_mode=handoff_mode,
                outbound_event_id=outbound_event_id,
                reason=handoff_decision.reason,
                source="backend_handoff_rule",
                is_turn_current=is_turn_current,
            )

        company_answer = self._build_company_faq_answer(customer_text)
        if company_answer and (self.deterministic_company_faq_enabled or not self.openai_service.enabled):
            self._append_bot_message(
                session,
                external_chat_id=external_chat_id,
                text=company_answer,
                outbound_event_id=outbound_event_id,
                payload={"source": "backend_company_faq"},
            )
            return AssistantReply(text=company_answer)
        if company_answer:
            return self._reply_from_company_faq(
                session,
                external_chat_id=external_chat_id,
                customer_text=customer_text,
                safe_answer=company_answer,
                outbound_event_id=outbound_event_id,
                is_turn_current=is_turn_current,
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
                is_turn_current=is_turn_current,
            )

        if not self.openai_service.enabled:
            return self._fallback_without_llm(
                session,
                external_chat_id=external_chat_id,
                customer_text=customer_text,
                outbound_event_id=outbound_event_id,
                is_turn_current=is_turn_current,
            )

        dialog_messages = self._get_provider_safe_llm_messages(session, external_chat_id)
        runtime_context = self._build_runtime_context(
            session,
            external_chat_id=external_chat_id,
            customer_text=customer_text,
            handoff_mode=handoff_mode,
        )
        messages = build_llm_messages(dialog_messages=dialog_messages, runtime_context=runtime_context)
        llm_request_id = self._new_llm_request_id(external_chat_id, "direct")
        self._log_llm_debug_event(
            "llm_request_started",
            {
                "llm_request_id": llm_request_id,
                "external_chat_id": external_chat_id,
                "customer_text": customer_text,
                "mode": "tool_auto",
                "tool_choice": "auto",
                "has_tools": True,
            },
        )
        self._log_llm_debug_event(
            "llm_direct_request",
            {
                "llm_request_id": llm_request_id,
                "external_chat_id": external_chat_id,
                "customer_text": customer_text,
                "transcript": transcript,
                "runtime_context": runtime_context,
                "messages": messages,
                "tools": self._summarize_tools(OPENAI_TOOLS),
                "tool_choice": "auto",
                "note": "Dialog history is sent as role-based messages; current customer message is the last role=user item.",
            },
        )
        first_turn = self.openai_service.run_messages(messages=messages, tools=OPENAI_TOOLS, tool_choice="auto")
        self._log_llm_debug_event(
            "llm_response_received",
            {
                "llm_request_id": llm_request_id,
                "external_chat_id": external_chat_id,
                "customer_text": customer_text,
                "mode": "tool_auto",
                "has_text": bool(first_turn.text),
                "tool_calls_count": len(first_turn.tool_calls),
                "error_type": first_turn.error_type,
                "retryable": first_turn.retryable,
            },
        )
        self._log_llm_debug_event(
            "llm_direct_response",
            {
                "llm_request_id": llm_request_id,
                "external_chat_id": external_chat_id,
                "customer_text": customer_text,
                "text": first_turn.text,
                "tool_calls": self._serialize_tool_calls(first_turn.tool_calls),
            },
        )
        self._log_tool_turn(customer_text=customer_text, turn=first_turn)

        if self._turn_is_stale(is_turn_current):
            return self._superseded_reply()

        tool_reply = self._handle_tool_calls(
            session,
            external_chat_id=external_chat_id,
            customer_text=customer_text,
            transcript=transcript,
            tool_calls=first_turn.tool_calls,
            outbound_event_id=outbound_event_id,
            handoff_mode=handoff_mode,
            is_turn_current=is_turn_current,
        )
        if tool_reply is not None:
            return tool_reply

        reply_text = first_turn.text
        if not reply_text:
            if first_turn.error_type:
                reply_text = PROVIDER_DELAY_TEXT
            else:
                reply_text = ARTICLE_REQUIRED_TEXT if self._is_price_stock_request(customer_text) else SAFE_FALLBACK_TEXT
        reply_text = self._sanitize_customer_reply(reply_text)

        handoff_reason = None
        if self._reply_claims_handoff(reply_text):
            handoff_reason = "bot_uncertain"
            self._register_handoff_action(
                session,
                external_chat_id=external_chat_id,
                reason=handoff_reason,
                handoff_mode=handoff_mode,
                source="llm_text_handoff_guard",
            )

        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=reply_text,
            outbound_event_id=outbound_event_id,
            payload={
                "source": "llm_direct" if first_turn.text else "llm_provider_error" if first_turn.error_type else "fallback",
                "provider_error": first_turn.error_type,
                "handoff_reason": handoff_reason,
                "backend_actions": self._build_handoff_backend_actions(handoff_reason, handoff_mode)
                if handoff_reason
                else None,
            },
        )
        return AssistantReply(text=reply_text, handoff_reason=handoff_reason)

    def _reply_from_company_faq(
        self,
        session,
        *,
        external_chat_id: str,
        customer_text: str,
        safe_answer: str,
        outbound_event_id: str | None,
        is_turn_current=None,
    ) -> AssistantReply:
        if self._turn_is_stale(is_turn_current):
            return self._superseded_reply()

        messages = build_company_faq_messages(customer_text=customer_text, safe_answer=safe_answer)
        llm_request_id = self._new_llm_request_id(external_chat_id, "company_faq")
        self._log_llm_debug_event(
            "llm_request_started",
            {
                "llm_request_id": llm_request_id,
                "external_chat_id": external_chat_id,
                "customer_text": customer_text,
                "mode": "company_faq_rewrite",
                "tool_choice": "none",
                "has_tools": False,
            },
        )
        self._log_llm_debug_event(
            "llm_company_faq_request",
            {
                "llm_request_id": llm_request_id,
                "external_chat_id": external_chat_id,
                "customer_text": customer_text,
                "safe_answer": safe_answer,
                "messages": messages,
            },
        )
        turn = self.openai_service.run_messages(messages=messages)
        self._log_llm_debug_event(
            "llm_response_received",
            {
                "llm_request_id": llm_request_id,
                "external_chat_id": external_chat_id,
                "customer_text": customer_text,
                "mode": "company_faq_rewrite",
                "has_text": bool(turn.text),
                "tool_calls_count": len(turn.tool_calls),
                "error_type": turn.error_type,
                "retryable": turn.retryable,
            },
        )

        reply_text = turn.text or safe_answer
        reply_text = self._sanitize_customer_reply(reply_text)
        source = "llm_company_faq" if turn.text else "backend_company_faq_fallback"
        if self._company_reply_violates_facts(reply_text):
            reply_text = safe_answer
            source = "backend_company_faq_guard"

        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=reply_text,
            outbound_event_id=outbound_event_id,
            payload={
                "source": source,
                "provider_error": turn.error_type,
                "safe_answer": safe_answer,
            },
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
        is_turn_current=None,
    ) -> AssistantReply | None:
        if self._turn_is_stale(is_turn_current):
            return self._superseded_reply()

        for index, call in enumerate(tool_calls, start=1):
            if not call.call_id:
                call.call_id = f"call_{call.name}_{index}"

            if call.name == "handoff_to_manager":
                reason = str(call.arguments.get("reason") or "llm_requested_manager")
                return self._handoff_reply(
                    session,
                    external_chat_id=external_chat_id,
                    handoff_mode=handoff_mode,
                    outbound_event_id=outbound_event_id,
                    reason=reason,
                    source="llm_tool",
                    is_turn_current=is_turn_current,
                )

            if call.name != "search_products":
                continue

            queries = call.arguments.get("queries", [])
            if not isinstance(queries, list):
                queries = []
            queries = [str(item).strip() for item in queries if str(item).strip()]
            if not queries:
                continue

            self._append_assistant_tool_call_message(
                session,
                external_chat_id=external_chat_id,
                tool_calls=[call],
            )
            lookup_result = self._search_products_by_queries(
                session,
                queries=queries,
                reason=str(call.arguments.get("intent") or call.arguments.get("reason") or "unknown"),
                customer_text=customer_text,
            )
            tool_result_message = OpenAIService.build_tool_result_message(
                tool_call_id=call.call_id,
                name="search_products",
                result={
                    "tool_name": "search_products",
                    "status": "ok",
                    "request": call.arguments,
                    "result": self._build_llm_product_lookup_result(lookup_result, customer_text=customer_text),
                },
            )
            self._append_tool_result_message(
                session,
                external_chat_id=external_chat_id,
                message=tool_result_message,
                tool_name="search_products",
                raw_product_lookup_result=lookup_result,
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
                include_tool_results_system=False,
                is_turn_current=is_turn_current,
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
        include_tool_results_system: bool = True,
        is_turn_current=None,
    ) -> AssistantReply:
        if self._turn_is_stale(is_turn_current):
            return self._superseded_reply()

        corporate_price_requested = self._is_corporate_price_request(customer_text)
        product_lookup_result = self._apply_response_policy(
            product_lookup_result,
            show_corporate_price=self.show_corporate_price and corporate_price_requested,
        )
        followup_refinement = self._build_followup_refinement_context(customer_text, product_lookup_result)
        product_lookup_result = self._apply_followup_refinement(product_lookup_result, followup_refinement)
        stock_only_request = self._is_stock_only_request(customer_text)
        product_lookup_result = self._apply_stock_only_policy(product_lookup_result, stock_only_request)
        requested_quantity = self._extract_requested_quantity(customer_text)
        stock_handoff_reason = self._get_stock_shortage_reason(product_lookup_result, requested_quantity)
        corporate_price_handoff_reason = "corporate_price_request" if corporate_price_requested and not self.show_corporate_price else None
        handoff_reason = stock_handoff_reason or force_handoff_reason or corporate_price_handoff_reason
        backend_actions = {
            "search_products_called": True,
            "handoff_to_manager_called": bool(handoff_reason),
            "handoff_reason": handoff_reason,
            "response_mode": self._resolve_response_mode(handoff_reason, stock_only_request=stock_only_request),
            "requested_quantity": requested_quantity,
            "show_corporate_price": self.show_corporate_price,
            "corporate_price_request": corporate_price_requested,
            "queried_by_code": self._lookup_queried_by_code(customer_text, product_lookup_result),
            "stock_only_request": stock_only_request,
            "followup_refinement": followup_refinement,
        }

        prelookup_tool_persisted = False
        if include_tool_results_system:
            self._append_backend_prelookup_tool_history(
                session,
                external_chat_id=external_chat_id,
                product_lookup_result=product_lookup_result,
                customer_text=customer_text,
            )
            include_tool_results_system = False
            prelookup_tool_persisted = True

        turn = None
        if self.openai_service.enabled:
            dialog_messages = self._get_provider_safe_llm_messages(session, external_chat_id)
            runtime_context = self._build_runtime_context(
                session,
                external_chat_id=external_chat_id,
                customer_text=customer_text,
                handoff_mode=handoff_mode,
                product_lookup_result=product_lookup_result,
                backend_actions=backend_actions,
            )
            fact_messages = build_product_facts_messages(
                dialog_messages=dialog_messages,
                runtime_context=runtime_context,
                product_lookup_result=product_lookup_result,
                backend_actions=backend_actions,
                include_tool_results_system=include_tool_results_system,
            )
            llm_request_id = self._new_llm_request_id(external_chat_id, "product_facts")
            self._log_llm_debug_event(
                "llm_request_started",
                {
                    "llm_request_id": llm_request_id,
                    "external_chat_id": external_chat_id,
                    "customer_text": customer_text,
                    "mode": "backend_prelookup_final_answer",
                    "tool_choice": "none",
                    "has_tools": False,
                    "has_tool_results_json": include_tool_results_system,
                    "prelookup_tool_persisted": prelookup_tool_persisted,
                },
            )
            self._log_llm_debug_event(
                "product_facts_request",
                {
                    "llm_request_id": llm_request_id,
                    "external_chat_id": external_chat_id,
                    "customer_text": customer_text,
                    "transcript": transcript,
                    "runtime_context": runtime_context,
                    "product_lookup_result": product_lookup_result,
                    "backend_actions": backend_actions,
                    "messages": fact_messages,
                    "note": (
                        "messages is the exact role-based payload sent to the LLM. "
                        "Dialog history is sent as user/assistant/tool messages; current customer message is not duplicated. "
                        "Backend prelookup results are persisted as synthetic assistant tool_call + role=tool before final generation; no tools are passed."
                    ),
                },
            )
            turn = self.openai_service.run_messages(messages=fact_messages)
            self._log_llm_debug_event(
                "llm_response_received",
                {
                    "llm_request_id": llm_request_id,
                    "external_chat_id": external_chat_id,
                    "customer_text": customer_text,
                    "mode": "backend_prelookup_final_answer",
                    "has_text": bool(turn.text),
                    "tool_calls_count": len(turn.tool_calls),
                    "error_type": turn.error_type,
                    "retryable": turn.retryable,
                },
            )
            self._log_llm_debug_event(
                "product_facts_response",
                {
                    "llm_request_id": llm_request_id,
                    "external_chat_id": external_chat_id,
                    "customer_text": customer_text,
                    "text": turn.text,
                    "tool_calls": self._serialize_tool_calls(turn.tool_calls),
                },
            )

        if self._turn_is_stale(is_turn_current):
            return self._superseded_reply()

        reply_text = (turn.text if turn else None) or self._build_programmatic_lookup_fallback(
            product_lookup_result,
            customer_text=customer_text,
            backend_actions=backend_actions,
        )
        reply_text = self._ensure_refinement_code_text(reply_text, product_lookup_result)
        reply_text = self._sanitize_customer_reply(reply_text)

        if not handoff_reason and self._reply_claims_handoff(reply_text):
            handoff_reason = "bot_uncertain"
            backend_actions["handoff_to_manager_called"] = True
            backend_actions["handoff_reason"] = handoff_reason
            backend_actions["response_mode"] = self._resolve_response_mode(handoff_reason, stock_only_request=stock_only_request)

        if handoff_reason:
            self._register_handoff_action(
                session,
                external_chat_id=external_chat_id,
                reason=handoff_reason,
                handoff_mode=handoff_mode,
                source=f"{payload_source}_handoff",
            )
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
                "product_lookup_result": product_lookup_result,
                "backend_actions": backend_actions,
                "handoff_reason": handoff_reason,
            },
        )
        return AssistantReply(text=reply_text, handoff_reason=handoff_reason)

    @staticmethod
    def _apply_response_policy(product_lookup_result: dict, *, show_corporate_price: bool) -> dict:
        payload = deepcopy(product_lookup_result)
        if show_corporate_price:
            return payload

        for container in AssistantService._iter_lookup_result_containers(payload):
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
    def _strip_similar_when_exact_found(product_lookup_result: dict) -> dict:
        payload = deepcopy(product_lookup_result)
        for container in AssistantService._iter_lookup_result_containers(payload):
            exact = container.get("exact_matches") or []
            if not exact:
                continue
            container["similar_matches"] = []
            container["similar_matches_count"] = 0
        if payload.get("exact_matches"):
            payload["similar_matches"] = []
            payload["similar_matches_count"] = 0
        summary = payload.get("summary")
        if isinstance(summary, dict) and (payload.get("exact_matches") or summary.get("total_exact_matches")):
            summary["total_similar_matches"] = 0
        return payload

    @staticmethod
    def _apply_stock_only_policy(product_lookup_result: dict, stock_only_request: bool) -> dict:
        if not stock_only_request:
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
    def _resolve_response_mode(handoff_reason: str | None, *, stock_only_request: bool = False) -> str | None:
        if stock_only_request:
            return "stock_only"
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
    def _collect_pending_client_messages(messages: list) -> list:
        last_bot_index = -1
        for index, message in enumerate(messages):
            if message.sender_role == "bot":
                last_bot_index = index
        return [message for message in messages[last_bot_index + 1 :] if message.sender_role == "client"]

    @staticmethod
    def _turn_is_stale(is_turn_current) -> bool:
        return is_turn_current is not None and not is_turn_current()

    @staticmethod
    def _superseded_reply() -> AssistantReply:
        return AssistantReply(text="", superseded=True)

    @staticmethod
    def _reply_claims_handoff(reply_text: str) -> bool:
        text = reply_text.lower()
        return (
            ("передаю" in text and ("менеджер" in text or "специалист" in text))
            or ("подключится к диалогу" in text and ("менеджер" in text or "специалист" in text))
        )

    @staticmethod
    def _company_reply_violates_facts(reply_text: str) -> bool:
        text = reply_text.lower()
        forbidden_fragments = (
            "ai",
            "виртуальн",
            "интеллектуальн",
            "характеристик",
            "размер",
            "фасов",
            "совместим",
            "аналог",
            "подбор",
            "деко-лайн",
            "северо-запад",
            "09:00",
        )
        return any(fragment in text for fragment in forbidden_fragments)

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
    def _ensure_refinement_code_text(reply_text: str, product_lookup_result: dict) -> str:
        refinement = product_lookup_result.get("resolved_followup_refinement") or {}
        code = str(refinement.get("code") or "").strip()
        if not code or code in reply_text:
            return reply_text
        return f"{reply_text} Код товара {code}."

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
        text = re.sub(r"\bссылку или фото\b", "код товара с сайта или цену в карточке", text, flags=re.IGNORECASE)
        text = re.sub(r"\bссылку/фото\b", "код товара с сайта или цену в карточке", text, flags=re.IGNORECASE)
        text = re.sub(r"\b([Кк]од(?:у|ом)?)(\d+)\b", r"\1 \2", text)
        text = re.sub(r"\b[Рр]озничная цена:\s*", "Розничная цена ", text)
        text = re.sub(r"\b[Кк]орпоративная цена:\s*", "корпоративная цена ", text)
        text = re.sub(r"\b[Вв] наличии:\s*", "В наличии ", text)
        text = re.sub(r"\b[Аа]ртикул:\s*", "Артикул ", text)
        text = re.sub(r"\b[Кк]од:\s*", "Код ", text)
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
        is_turn_current=None,
    ) -> AssistantReply:
        if self._turn_is_stale(is_turn_current):
            return self._superseded_reply()

        reply_text = ARTICLE_REQUIRED_TEXT if self._is_price_stock_request(customer_text) else SAFE_FALLBACK_TEXT
        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=reply_text,
            outbound_event_id=outbound_event_id,
            payload={"source": "fallback_without_llm"},
        )
        return AssistantReply(text=reply_text)

    @staticmethod
    def _build_company_faq_answer(customer_text: str) -> str | None:
        text = customer_text.lower()
        wants_address = "адрес" in text or "где вы" in text or "находит" in text
        wants_contact = any(keyword in text for keyword in ("как связ", "контакт", "телефон", "номер", "почт", "email"))
        if wants_address and wants_contact:
            return (
                "Мы находимся по адресу: Санкт-Петербург, ул. Якорная, д. 15, лит. Б. "
                "Телефон: +7 (812) 372-66-07, email: market@amix.spb.ru."
            )
        if any(keyword in text for keyword in ("достав", "транспорт", "пвз", "самовывоз")):
            return (
                "Да, доставляем по России: возможны транспортные компании, пункты выдачи и курьерская доставка. "
                "Точную стоимость и условия под ваш заказ лучше уточнит менеджер."
            )
        if wants_contact:
            return "Можно позвонить по телефону +7 (812) 372-66-07 или написать на market@amix.spb.ru."
        if wants_address:
            return "Магазин находится по адресу: Санкт-Петербург, ул. Якорная, д. 15, лит. Б."
        if any(keyword in text for keyword in ("расскаж", "о себе", "о вас", "кто вы", "что за компания", "чем занимает")):
            return (
                "AMIX - магазин и поставщик мебельной фурнитуры, аксессуаров для мебели и комплектующих "
                "для кухонь и корпусной мебели. Компания работает с мебельной фурнитурой с 2000 года; "
                "в ассортименте более 10 000 наименований, собственные марки - AMIX, AGV, FIT."
            )
        if any(keyword in text for keyword in ("режим", "график", "часы работы")):
            return "Режим работы: Пн-Пт 9:30-18:00, Сб 10:00-17:00."
        if "возврат" in text and "суббот" in text:
            return "По субботам возврат товара не осуществляется. Лучше обратиться по возврату в рабочие дни."
        return None

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
            item = self._strip_similar_when_exact_found(item)
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

        result = {
            "queries": queries,
            "display_queries": [item.get("display_query") or item.get("query") for item in visible_query_results],
            "reason": reason,
            "request": {
                "queries": queries,
                "intent": reason,
                "use_dialog_context": self._looks_like_dialog_context_query(customer_text or ""),
                "context_note": self._build_search_context_note(customer_text or "", reason),
            },
            **best,
            "exact_matches": exact_matches or best.get("exact_matches", []),
            "similar_matches": similar_matches if exact_matches else best.get("similar_matches", []),
            "exact_matches_count": exact_count if exact_matches else best.get("exact_matches_count", 0),
            "similar_matches_count": 0 if exact_matches else best.get("similar_matches_count", 0),
            "summary": summary,
            "results": visible_query_results,
            "per_query_results": visible_query_results,
        }
        return self._strip_similar_when_exact_found(result)

    def _build_runtime_context(
        self,
        session,
        *,
        external_chat_id: str,
        customer_text: str | None = None,
        handoff_mode: str = "jivo",
        product_lookup_result: dict | None = None,
        backend_actions: dict | None = None,
    ) -> dict[str, Any]:
        recent_messages = list_recent_messages(session, external_chat_id, limit=self.dialog_service.history_limit)
        last_lookup = product_lookup_result or self._find_latest_product_lookup(recent_messages)
        active_product = self._extract_active_product(last_lookup)
        pending_clarification = self._extract_pending_clarification(last_lookup)
        product_memory = self._build_product_memory(recent_messages, active_product)

        return {
            "type": "amix_internal_context",
            "channel": "telegram_test" if external_chat_id.startswith("telegram:") else "jivo",
            "handoff_mode": handoff_mode,
            "settings": {
                "show_corporate_price": self.show_corporate_price,
                "show_price_on_availability_question": False,
                "handoff_enabled": True,
            },
            "dialog_state": {
                "active_product": active_product,
                "product_memory": product_memory,
                "pending_clarification": pending_clarification,
                "last_handoff_status": self._find_latest_handoff_status(recent_messages),
            },
            "backend_actions": backend_actions or {},
        }

    @staticmethod
    def _find_latest_product_lookup(messages: list) -> dict | None:
        for message in reversed(messages):
            lookup = AssistantService._extract_product_lookup_from_message(message)
            if lookup:
                return lookup
        return None

    @staticmethod
    def _find_latest_pending_product_lookup(messages: list) -> dict | None:
        for message in reversed(messages):
            lookup = AssistantService._extract_product_lookup_from_message(message)
            if lookup and AssistantService._extract_pending_clarification(lookup):
                return lookup
        return None

    @staticmethod
    def _extract_product_lookup_from_message(message) -> dict | None:
        payload = message.payload or {}
        for key in ("raw_product_lookup_result", "product_lookup_result"):
            lookup = payload.get(key)
            if isinstance(lookup, dict):
                return lookup

        if message.sender_role != "tool" or payload.get("tool_name") != "search_products":
            return None

        try:
            tool_payload = json.loads(message.text or "{}")
        except json.JSONDecodeError:
            return None
        if not isinstance(tool_payload, dict):
            return None

        raw_result = tool_payload.get("raw_result")
        if isinstance(raw_result, dict):
            return raw_result

        result = tool_payload.get("result")
        if isinstance(result, dict) and (
            "exact_matches" in result or "per_query_results" in result or "results" in result
        ):
            return result
        return None

    @staticmethod
    def _extract_active_product(product_lookup_result: dict | None) -> dict | None:
        if not product_lookup_result:
            return None
        exact = product_lookup_result.get("exact_matches") or []
        if len(exact) != 1:
            return None

        match = exact[0]
        return {
            "code": match.get("code"),
            "article": match.get("article"),
            "stock": match.get("stock"),
            "stock_display": AssistantService._format_quantity(match.get("stock"), match.get("unit")),
            "retail_price": match.get("retail_price"),
            "retail_price_display": AssistantService._format_price_text(match.get("retail_price_display"), match.get("retail_price")),
            "corporate_price": match.get("corporate_price"),
            "corporate_price_display": AssistantService._format_price_text(
                match.get("corporate_price_display"),
                match.get("corporate_price"),
            ),
            "unit": match.get("unit"),
            "weight": match.get("weight"),
            "volume": match.get("volume"),
            "discount_status": "unknown",
        }

    @staticmethod
    def _extract_pending_clarification(product_lookup_result: dict | None) -> dict | None:
        if not product_lookup_result:
            return None
        exact = product_lookup_result.get("exact_matches") or []
        if len(exact) < 2:
            return None
        articles = {str(item.get("article") or "").strip() for item in exact if item.get("article")}
        if len(articles) != 1:
            return None
        article = next(iter(articles))
        return {
            "type": "choose_product_variant",
            "article": article,
            "allowed_clarifications": ["code", "retail_price"],
        }

    @staticmethod
    def _resolve_pending_lookup_query(product_lookup_result: dict) -> str | None:
        pending = AssistantService._extract_pending_clarification(product_lookup_result)
        if pending and pending.get("article"):
            return str(pending["article"])
        for key in ("display_query", "query"):
            value = product_lookup_result.get(key)
            if value:
                return str(value)
        for value in product_lookup_result.get("display_queries") or product_lookup_result.get("queries") or []:
            if value:
                return str(value)
        return None

    @staticmethod
    def _build_product_memory(messages: list, active_product: dict | None, limit: int = 5) -> list[dict[str, Any]]:
        memory: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add_match(match: dict, source_message_id: Any = None) -> None:
            key = str(match.get("code") or match.get("article") or "").strip()
            if not key or key in seen:
                return
            item = AssistantService._compact_match_for_context(match)
            if source_message_id is not None:
                item["last_discussed_at_turn"] = f"message_{source_message_id}"
            memory.append(item)
            seen.add(key)

        if active_product:
            add_match(active_product, "active")

        for message in reversed(messages):
            lookup = AssistantService._extract_product_lookup_from_message(message)
            if not isinstance(lookup, dict):
                continue
            for match in lookup.get("exact_matches") or []:
                add_match(match, getattr(message, "id", None))
                if len(memory) >= limit:
                    return memory[:limit]
        return memory[:limit]

    @staticmethod
    def _compact_lookup_for_context(product_lookup_result: dict | None) -> dict | None:
        if not product_lookup_result:
            return None
        exact_matches = product_lookup_result.get("exact_matches", [])
        similar_matches = product_lookup_result.get("similar_matches", [])
        return {
            "status": product_lookup_result.get("status"),
            "query": product_lookup_result.get("display_query") or product_lookup_result.get("query"),
            "queries": product_lookup_result.get("queries"),
            "exact_matches_count": product_lookup_result.get("exact_matches_count"),
            "similar_matches_count": product_lookup_result.get("similar_matches_count"),
            "exact_matches": [AssistantService._compact_match_for_context(item) for item in exact_matches[:5]],
            "similar_matches": [AssistantService._compact_match_for_context(item) for item in similar_matches[:3]],
            "resolved_followup_refinement": product_lookup_result.get("resolved_followup_refinement"),
            "summary": product_lookup_result.get("summary"),
        }

    @staticmethod
    def _compact_match_for_context(match: dict) -> dict[str, Any]:
        return {
            "code": match.get("code"),
            "article": match.get("article"),
            "stock_display": AssistantService._format_quantity(match.get("stock"), match.get("unit")),
            "retail_price": match.get("retail_price"),
            "retail_price_display": AssistantService._format_price_text(match.get("retail_price_display"), match.get("retail_price")),
            "corporate_price": match.get("corporate_price"),
            "corporate_price_display": AssistantService._format_price_text(
                match.get("corporate_price_display"),
                match.get("corporate_price"),
            ),
            "unit": match.get("unit"),
            "discount_status": "unknown",
        }

    @staticmethod
    def _build_llm_product_lookup_result(product_lookup_result: dict, *, customer_text: str = "") -> dict[str, Any]:
        payload = AssistantService._strip_similar_when_exact_found(product_lookup_result)
        reason = str(payload.get("reason") or (payload.get("request") or {}).get("intent") or "product_info")
        status_map = {
            "exact_found": "точное_совпадение",
            "multiple_exact": "несколько_точных_позиций",
            "similar_found": "похожие_варианты",
            "not_found": "не_найдено",
            "invalid_query": "некорректный_запрос",
            "error": "ошибка",
        }
        task_map = {
            "availability": "наличие",
            "stock": "наличие",
            "price": "цена",
            "product_info": "информация_о_товаре",
            "compare": "сравнение",
            "order": "заказ",
            "discount_check": "скидка",
            "clarification": "уточнение_варианта",
        }

        def compact_match(match: dict) -> dict[str, Any]:
            result = {
                "код_товара": match.get("code"),
                "артикул": match.get("article"),
                "остаток": AssistantService._format_quantity(match.get("stock"), match.get("unit")),
                "единица": str(match.get("unit") or "").strip() or None,
            }
            retail_price = AssistantService._format_price_text(match.get("retail_price_display"), match.get("retail_price"))
            corporate_price = AssistantService._format_price_text(
                match.get("corporate_price_display"),
                match.get("corporate_price"),
            )
            if retail_price:
                result["розничная_цена"] = retail_price
            if corporate_price:
                result["корпоративная_цена"] = corporate_price
            if match.get("weight") is not None:
                result["вес"] = match.get("weight")
            if match.get("volume") is not None:
                result["объем"] = match.get("volume")
            return {key: value for key, value in result.items() if value not in (None, "")}

        def compact_container(container: dict) -> dict[str, Any]:
            exact = container.get("exact_matches") or []
            similar = [] if exact else container.get("similar_matches") or []
            return {
                "запрос_клиента": container.get("display_query") or container.get("query"),
                "статус": status_map.get(container.get("status"), container.get("status")),
                "товары": [compact_match(match) for match in exact],
                "похожие_варианты": [compact_match(match) for match in similar[:3]],
            }

        per_query_results = payload.get("results") or payload.get("per_query_results") or []
        result = {
            "тип": "результат_поиска_товаров",
            "задача": task_map.get(reason, reason),
            "статус": status_map.get(payload.get("status"), payload.get("status")),
            "запрос_клиента": payload.get("display_query") or payload.get("query"),
            "порядок_запросов_клиента": [
                item.get("display_query") or item.get("query")
                for item in per_query_results
                if item.get("display_query") or item.get("query")
            ],
            "товары": [compact_match(match) for match in (payload.get("exact_matches") or [])],
            "похожие_варианты": [
                compact_match(match)
                for match in ([] if payload.get("exact_matches") else (payload.get("similar_matches") or [])[:3])
            ],
        }

        if len(per_query_results) > 1:
            result["результаты_по_запросам"] = [compact_container(item) for item in per_query_results]

        refinement = payload.get("resolved_followup_refinement")
        if refinement:
            result["уточнение_выбрало"] = {
                "код_товара": refinement.get("code"),
                "артикул": refinement.get("article"),
                "значение": refinement.get("value"),
            }
        return {key: value for key, value in result.items() if value not in (None, [], {})}

    @staticmethod
    def _find_latest_handoff_status(messages: list) -> dict | None:
        for message in reversed(messages):
            payload = message.payload or {}
            reason = payload.get("handoff_reason")
            if reason:
                return {"handoff_reason": reason, "source": payload.get("source")}
        return None

    @staticmethod
    def _looks_like_dialog_context_query(customer_text: str) -> bool:
        text = customer_text.lower()
        keywords = ("скидк", "акци", "корпоратив", "всм", "в смысле", "я спросил", "цена", "код", "руб", "стоит")
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _build_search_context_note(customer_text: str, reason: str) -> str:
        if AssistantService._looks_like_dialog_context_query(customer_text):
            return f"Запрос может быть продолжением текущей темы диалога. Intent: {reason}."
        return f"Поиск выполнен по текущему сообщению клиента. Intent: {reason}."

    def _append_backend_prelookup_tool_history(
        self,
        session,
        *,
        external_chat_id: str,
        product_lookup_result: dict,
        customer_text: str,
    ) -> None:
        request = product_lookup_result.get("request") or {}
        call_arguments = {
            "queries": product_lookup_result.get("display_queries")
            or request.get("queries")
            or product_lookup_result.get("queries")
            or [product_lookup_result.get("display_query") or product_lookup_result.get("query")],
            "intent": product_lookup_result.get("reason") or request.get("intent") or "product_info",
            "use_dialog_context": bool(request.get("use_dialog_context")),
            "context_note": request.get("context_note") or self._build_search_context_note(customer_text, product_lookup_result.get("reason") or "product_info"),
            "source": "backend_prelookup",
        }
        call_id = f"prelookup_search_{int(datetime.now(UTC).timestamp() * 1000)}"
        call = ToolCall(name="search_products", arguments=call_arguments, call_id=call_id)
        self._append_assistant_tool_call_message(
            session,
            external_chat_id=external_chat_id,
            tool_calls=[call],
            source="backend_prelookup_tool_call",
        )
        tool_result_message = OpenAIService.build_tool_result_message(
            tool_call_id=call_id,
            name="search_products",
            result={
                "tool_name": "search_products",
                "mode": "backend_prelookup",
                "status": "ok",
                "request": call_arguments,
                "result": self._build_llm_product_lookup_result(product_lookup_result, customer_text=customer_text),
            },
        )
        self._append_tool_result_message(
            session,
            external_chat_id=external_chat_id,
            message=tool_result_message,
            tool_name="search_products",
            source="backend_prelookup_tool_result",
            raw_product_lookup_result=product_lookup_result,
        )

    def _register_handoff_action(
        self,
        session,
        *,
        external_chat_id: str,
        reason: str,
        handoff_mode: str,
        source: str,
    ) -> None:
        self.handoff_service.register_handoff(session, external_chat_id, reason)
        self._append_handoff_tool_history(
            session,
            external_chat_id=external_chat_id,
            reason=reason,
            handoff_mode=handoff_mode,
            source=source,
        )

    def _append_handoff_tool_history(
        self,
        session,
        *,
        external_chat_id: str,
        reason: str,
        handoff_mode: str,
        source: str,
    ) -> None:
        call_id = f"handoff_{int(datetime.now(UTC).timestamp() * 1000)}"
        call_arguments = {
            "reason": reason,
            "summary": f"Backend requested manager handoff. Reason: {reason}.",
            "customer_message": self._resolve_handoff_text(handoff_mode, reason),
            "handoff_mode": handoff_mode,
        }
        if handoff_mode == "demo":
            call_arguments["real_jivo_invite_sent"] = False

        call = ToolCall(name="handoff_to_manager", arguments=call_arguments, call_id=call_id)
        self._append_assistant_tool_call_message(
            session,
            external_chat_id=external_chat_id,
            tool_calls=[call],
            source=f"{source}_tool_call",
        )
        tool_result_message = OpenAIService.build_tool_result_message(
            tool_call_id=call_id,
            name="handoff_to_manager",
            result={
                "tool_name": "handoff_to_manager",
                "status": "ok",
                "reason": reason,
                "handoff_mode": handoff_mode,
                "real_jivo_invite_sent": False if handoff_mode == "demo" else None,
                "jivo_invite_requested": handoff_mode == "jivo",
            },
        )
        self._append_tool_result_message(
            session,
            external_chat_id=external_chat_id,
            message=tool_result_message,
            tool_name="handoff_to_manager",
            source=f"{source}_tool_result",
        )

    @staticmethod
    def _build_handoff_backend_actions(reason: str, handoff_mode: str) -> dict[str, Any]:
        return {
            "handoff_to_manager_called": True,
            "handoff_reason": reason,
            "handoff_mode": handoff_mode,
            "real_jivo_invite_sent": False if handoff_mode == "demo" else None,
            "jivo_invite_requested": handoff_mode == "jivo",
        }

    def _append_assistant_tool_call_message(
        self,
        session,
        *,
        external_chat_id: str,
        tool_calls: list,
        source: str = "llm_tool_call",
    ) -> None:
        message = OpenAIService.build_assistant_tool_call_message(tool_calls)
        append_message(
            session,
            external_chat_id=external_chat_id,
            sender_role="assistant_tool_call",
            text="",
            payload={
                "source": source,
                "content": message.get("content") or "",
                "tool_calls": message.get("tool_calls") or [],
            },
        )

    def _append_tool_result_message(
        self,
        session,
        *,
        external_chat_id: str,
        message: dict[str, Any],
        tool_name: str,
        source: str = "tool_result",
        raw_product_lookup_result: dict | None = None,
    ) -> None:
        payload = {
            "source": source,
            "tool_name": tool_name,
            "tool_call_id": message.get("tool_call_id"),
            "content": message.get("content"),
        }
        if raw_product_lookup_result is not None:
            payload["raw_product_lookup_result"] = raw_product_lookup_result
        append_message(
            session,
            external_chat_id=external_chat_id,
            sender_role="tool",
            text=str(message.get("content") or ""),
            payload=payload,
        )

    def _handoff_reply(
        self,
        session,
        *,
        external_chat_id: str,
        handoff_mode: str,
        outbound_event_id: str | None,
        reason: str,
        source: str,
        is_turn_current=None,
    ) -> AssistantReply:
        if self._turn_is_stale(is_turn_current):
            return self._superseded_reply()

        self._register_handoff_action(
            session,
            external_chat_id=external_chat_id,
            reason=reason,
            handoff_mode=handoff_mode,
            source=source,
        )
        handoff_text = self._resolve_handoff_text(handoff_mode, reason)
        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=self._sanitize_customer_reply(handoff_text),
            outbound_event_id=outbound_event_id,
            payload={
                "source": source,
                "handoff_reason": reason,
                "backend_actions": self._build_handoff_backend_actions(reason, handoff_mode),
            },
        )
        return AssistantReply(text=self._sanitize_customer_reply(handoff_text), handoff_reason=reason)

    def _handoff_already_requested_reply(
        self,
        session,
        *,
        external_chat_id: str,
        outbound_event_id: str | None,
    ) -> AssistantReply:
        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=HANDOFF_ALREADY_REQUESTED_TEXT,
            outbound_event_id=outbound_event_id,
            payload={"source": "handoff_already_requested", "handoff_already_requested": True},
        )
        return AssistantReply(text=HANDOFF_ALREADY_REQUESTED_TEXT)

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
        has_price_intent = any(keyword in text for keyword in ("цен", "стоит", "стоим", "руб", "корп", "опт", "дешев", "дороже"))
        has_order_intent = any(keyword in text for keyword in ("заказ", "купить", "оформ"))
        return has_stock_intent and not has_price_intent and not has_order_intent

    @staticmethod
    def _guess_lookup_reason(customer_text: str) -> str:
        text = customer_text.lower()
        if "цен" in text or "стоит" in text or "дешев" in text or "дороже" in text:
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
    def _extract_recent_lookup_article_candidates(messages: list) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for message in reversed(messages):
            lookup = AssistantService._extract_product_lookup_from_message(message)
            if not lookup:
                continue
            for match in lookup.get("exact_matches") or []:
                article = str(match.get("article") or "").strip()
                if not article:
                    continue
                normalized = normalize_article(article)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                result.append(article)
                if len(result) >= 5:
                    return result
        return result

    @staticmethod
    def _is_short_numeric_query_only(article_candidates: list[str]) -> bool:
        if not article_candidates:
            return False
        return all(re.fullmatch(r"\d{1,6}(?:[,.]\d{1,2})?", str(candidate).strip()) for candidate in article_candidates)

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

    @staticmethod
    def _looks_like_explicit_history_article_followup(customer_text: str) -> bool:
        if not AssistantService._looks_like_history_product_followup(customer_text):
            return False
        normalized_text = normalize_article(customer_text)
        return bool(normalized_text and not normalized_text.isdigit())

    @staticmethod
    def _looks_like_history_product_followup(customer_text: str) -> bool:
        text = customer_text.lower()
        return any(
            keyword in text
            for keyword in (
                "дешев",
                "дороже",
                "подешевле",
                "вариант",
                "такие",
                "те котор",
                "сперва",
                "мп",
            )
        )

    @staticmethod
    def _select_history_candidates_for_followup(customer_text: str, candidates: list[str]) -> list[str]:
        normalized_text = normalize_article(customer_text)
        if "МП" in normalized_text:
            matched = [candidate for candidate in candidates if "МП" in normalize_article(candidate)]
            if matched:
                return matched[:2]
        return candidates[:2]

    @staticmethod
    def _sort_queries_by_text_order(queries: list[str], customer_text: str | None) -> list[str]:
        if not customer_text or len(queries) < 2:
            return queries

        text_lower = customer_text.lower()
        ordered: list[tuple[int, int, str]] = []
        for index, query in enumerate(queries):
            display_query = AssistantService._resolve_display_query(query, customer_text)
            position = text_lower.find(str(display_query or "").lower()) if display_query else -1
            if position < 0:
                position = text_lower.find(str(query).lower())
            ordered.append((position if position >= 0 else 1_000_000 + index, index, query))
        return [query for _, _, query in sorted(ordered)]

    @staticmethod
    def _resolve_contextual_product_followup_queries(customer_text: str, messages: list) -> list[str]:
        lookup = AssistantService._find_latest_product_lookup(messages)
        if not lookup:
            return []

        per_query_results = lookup.get("per_query_results") or lookup.get("results") or []
        if not per_query_results:
            return []

        ordinal_index = AssistantService._extract_followup_ordinal_index(customer_text)
        if ordinal_index is not None and 0 <= ordinal_index < len(per_query_results):
            query = AssistantService._preferred_query_for_lookup_item(per_query_results[ordinal_index])
            return [query] if query else []

        normalized_fragments = [normalize_article(candidate) for candidate in extract_article_candidates(customer_text)]
        normalized_fragments = [fragment for fragment in normalized_fragments if len(fragment) >= 3]
        if not normalized_fragments:
            return []

        for item in per_query_results:
            values = [
                item.get("display_query"),
                item.get("query"),
                item.get("raw_backend_query"),
            ]
            for match in (item.get("exact_matches") or []) + (item.get("similar_matches") or []):
                values.extend([match.get("article"), match.get("code")])

            normalized_values = [normalize_article(str(value)) for value in values if value]
            for fragment in normalized_fragments:
                if any(fragment in value or value in fragment for value in normalized_values if value):
                    query = AssistantService._preferred_query_for_lookup_item(item)
                    return [query] if query else []
        return []

    @staticmethod
    def _extract_followup_ordinal_index(customer_text: str) -> int | None:
        text = customer_text.lower()
        if re.search(r"\b(1|перв\w*)\b", text):
            return 0
        if re.search(r"\b(2|вт[оа]+р\w*)\b", text):
            return 1
        return None

    @staticmethod
    def _preferred_query_for_lookup_item(item: dict) -> str | None:
        exact = item.get("exact_matches") or []
        if len(exact) == 1:
            match = exact[0]
            return str(match.get("article") or match.get("code") or "").strip() or None
        return str(item.get("display_query") or item.get("query") or item.get("raw_backend_query") or "").strip() or None

    def _log_lookup_result(self, *, stage: str, payload: dict[str, Any]) -> None:
        if self.debug_lookup_logs:
            logger.info("assistant_lookup_%s payload=%s", stage, json.dumps(payload, ensure_ascii=False))

    def _get_provider_safe_llm_messages(self, session, external_chat_id: str) -> list[dict]:
        messages = self.dialog_service.get_llm_messages(session, external_chat_id)
        if self.openai_service.provider != "google_ai_studio":
            return messages
        return self._convert_tool_history_to_system_messages(messages)

    @staticmethod
    def _convert_tool_history_to_system_messages(messages: list[dict]) -> list[dict]:
        converted: list[dict] = []
        for message in messages:
            if message.get("role") == "assistant" and message.get("tool_calls"):
                continue
            if message.get("role") == "tool":
                content = str(message.get("content") or "").strip()
                if content:
                    converted.append({"role": "system", "content": f"TOOL_RESULTS_JSON:\n{content}"})
                continue
            converted.append(message)
        return converted

    @staticmethod
    def _new_llm_request_id(external_chat_id: str, mode: str) -> str:
        safe_chat_id = re.sub(r"[^A-Za-z0-9_.:-]+", "_", external_chat_id)[:80]
        timestamp_ms = int(datetime.now(UTC).timestamp() * 1000)
        return f"{mode}:{safe_chat_id}:{timestamp_ms}"

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
        show_corporate_price = bool(backend_actions.get("show_corporate_price", True) and backend_actions.get("corporate_price_request"))
        stock_only_request = bool(backend_actions.get("stock_only_request") or backend_actions.get("response_mode") == "stock_only")

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
                        price_text = ""
                        if not stock_only_request:
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
                if stock_only_request:
                    parts.append("По цене тоже подсказать?")
                elif retail_price:
                    parts.append(f"Розничная цена {retail_price}.")
                if corporate_price:
                    parts.append(f"Корпоративная цена {corporate_price}.")
                if not stock_only_request and not retail_price and not corporate_price:
                    parts.append("Цена в текущих данных не указана.")
                return " ".join(parts)

            display_query = AssistantService._display_query_for_matches(query, exact)
            if "дешев" in customer_text.lower():
                priced_matches = [
                    match for match in exact if AssistantService._format_price_text(match.get("retail_price_display"), match.get("retail_price"))
                ]
                priced_matches.sort(
                    key=lambda match: float(str(match.get("retail_price") or "0").replace(",", ".") or 0)
                )
                if priced_matches:
                    variants = "; ".join(
                        (
                            f"код {match.get('code') or '-'} — "
                            f"{AssistantService._format_price_text(match.get('retail_price_display'), match.get('retail_price'))}, "
                            f"остаток {AssistantService._format_quantity(match.get('stock'), match.get('unit'))}"
                        )
                        for match in priced_matches[:3]
                    )
                    return f"По {display_query} есть такие варианты по цене: {variants}. Если нужен один из них, пришлите код товара."
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
            text = str(display_value).strip().rstrip(".")
            return AssistantService._format_price_spacing(text)
        number = AssistantService._format_number(raw_value)
        if not number:
            return None
        return f"{number} руб"

    @staticmethod
    def _format_price_spacing(text: str) -> str:
        def replace(match: re.Match) -> str:
            whole = re.sub(r"\s+", "", match.group("whole"))
            fraction = match.group("fraction") or ""
            if not whole.isdigit():
                return match.group(0)
            grouped = f"{int(whole):,}".replace(",", " ")
            return f"{grouped}{fraction}"

        return re.sub(r"(?P<whole>\d+(?:\s\d{3})*)(?P<fraction>[,.]\d+)?", replace, text, count=1)

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
