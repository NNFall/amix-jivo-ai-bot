from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import json
import logging
from pathlib import Path
import re
from typing import Any

from database.repositories import (
    append_message,
    create_llm_call,
    get_chat_by_external_id,
    get_or_create_chat,
    get_or_create_customer,
    list_messages,
    message_exists_by_external_event_id,
    search_products_structured,
)
from llm.openai_client import OpenAIService, ToolCall
from llm.prompts import build_llm_messages
from llm.tool_schemas import OPENAI_TOOLS
from settings import get_settings

from .dialog_service import DialogService
from .handoff_service import HandoffService


logger = logging.getLogger(__name__)

PROVIDER_DELAY_TEXT = (
    "Сейчас автоматическая проверка задерживается. Попробуйте, пожалуйста, ещё раз чуть позже "
    "или позовите менеджера."
)
HANDOFF_TEXT = "Передаю вопрос менеджеру. Он подключится к диалогу и поможет вам."
HANDOFF_ALREADY_REQUESTED_TEXT = "Менеджер уже вызван, он подключится к диалогу."
MAX_MODEL_ROUNDS = 5
ALLOWED_TOOL_NAMES = {"search_products", "handoff_to_manager"}


@dataclass(slots=True)
class AssistantReply:
    text: str
    handoff_reason: str | None = None
    superseded: bool = False


class AssistantService:
    """Persist the dialog and execute the two tools selected by the model."""

    def __init__(self) -> None:
        settings = get_settings()
        self.dialog_service = DialogService()
        self.handoff_service = HandoffService()
        self.openai_service = OpenAIService(settings)
        self.debug_lookup_logs = settings.assistant_debug_lookup_logs
        self.debug_llm_payloads = settings.assistant_debug_llm_payloads
        self.debug_llm_payloads_path = Path(settings.assistant_debug_llm_payloads_path)

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
        if inbound_event_id and message_exists_by_external_event_id(session, inbound_event_id):
            return chat.external_chat_id
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
        if chat is None or chat.status in {"agent_joined", "closed"}:
            return self._superseded_reply()
        if chat.status == "handoff_requested":
            return self._handoff_already_requested_reply(
                session,
                external_chat_id=external_chat_id,
                outbound_event_id=outbound_event_id,
            )

        pending_messages = self._collect_pending_client_messages(list_messages(session, external_chat_id))
        if not pending_messages:
            return self._superseded_reply()

        if not self.openai_service.enabled:
            return self._store_text_reply(
                session,
                external_chat_id=external_chat_id,
                outbound_event_id=outbound_event_id,
                text=PROVIDER_DELAY_TEXT,
                source="llm_disabled",
            )

        return self._handle_model_turns(
            session,
            external_chat_id=external_chat_id,
            outbound_event_id=outbound_event_id,
            handoff_mode=handoff_mode,
            is_turn_current=is_turn_current,
        )

    def _handle_model_turns(
        self,
        session,
        *,
        external_chat_id: str,
        outbound_event_id: str | None,
        handoff_mode: str,
        is_turn_current=None,
    ) -> AssistantReply:
        for round_index in range(1, MAX_MODEL_ROUNDS + 1):
            if self._turn_is_stale(is_turn_current):
                return self._discard_model_turn_and_supersede(
                    session,
                    external_chat_id=external_chat_id,
                    turn_id=outbound_event_id,
                )

            messages = build_llm_messages(
                dialog_messages=self.dialog_service.get_llm_messages(session, external_chat_id)
            )
            request_id = self._new_llm_request_id(external_chat_id, f"model_turn_{round_index}")
            self._log_llm_debug_event(
                "llm_request_started",
                {
                    "request_id": request_id,
                    "external_chat_id": external_chat_id,
                    "round": round_index,
                    "messages": messages,
                    "tools": self._summarize_tools(OPENAI_TOOLS),
                },
            )
            turn = self._run_llm_messages(
                session,
                external_chat_id=external_chat_id,
                outbound_event_id=outbound_event_id,
                request_id=request_id,
                messages=messages,
            )
            if self._turn_is_stale(is_turn_current):
                return self._discard_model_turn_and_supersede(
                    session,
                    external_chat_id=external_chat_id,
                    turn_id=outbound_event_id,
                )

            if not turn.tool_calls:
                text = (turn.text or PROVIDER_DELAY_TEXT).strip()
                reply = self._store_text_reply(
                    session,
                    external_chat_id=external_chat_id,
                    outbound_event_id=outbound_event_id,
                    text=text,
                    source="llm_model",
                    extra_payload={"provider_error": turn.error_type},
                )
                if self._turn_is_stale(is_turn_current):
                    return self._discard_model_turn_and_supersede(
                        session,
                        external_chat_id=external_chat_id,
                        turn_id=outbound_event_id,
                    )
                return reply

            calls = self._prepare_tool_calls(turn.tool_calls, round_index=round_index)
            self._append_assistant_tool_call_message(
                session,
                external_chat_id=external_chat_id,
                tool_calls=calls,
                content=turn.text or "",
                turn_id=outbound_event_id,
            )

            handoff: tuple[str, str] | None = None
            for call in calls:
                if call.name == "search_products":
                    result = self._execute_search_products(session, call.arguments)
                elif call.name == "handoff_to_manager":
                    reason = str(call.arguments.get("reason") or "bot_uncertain")
                    summary = str(call.arguments.get("summary") or "").strip()
                    if handoff_mode == "demo":
                        self.handoff_service.register_handoff(session, external_chat_id, reason)
                    result = {
                        "tool_name": "handoff_to_manager",
                        "status": "ok" if handoff_mode == "demo" else "pending_external_invite",
                        "reason": reason,
                        "summary": summary,
                        "handoff_mode": handoff_mode,
                        "real_jivo_invite_sent": False if handoff_mode == "demo" else None,
                        "jivo_invite_requested": handoff_mode == "jivo",
                    }
                    customer_message = str(call.arguments.get("customer_message") or "").strip()
                    handoff = (reason, customer_message or HANDOFF_TEXT)
                else:
                    result = {
                        "tool_name": call.name,
                        "status": "unsupported_tool",
                        "allowed_tools": sorted(ALLOWED_TOOL_NAMES),
                    }

                self._append_tool_result_message(
                    session,
                    external_chat_id=external_chat_id,
                    call=call,
                    result=result,
                    turn_id=outbound_event_id,
                )

                if self._turn_is_stale(is_turn_current):
                    return self._discard_model_turn_and_supersede(
                        session,
                        external_chat_id=external_chat_id,
                        turn_id=outbound_event_id,
                    )

            if handoff is not None:
                reason, customer_message = handoff
                reply = self._store_text_reply(
                    session,
                    external_chat_id=external_chat_id,
                    outbound_event_id=outbound_event_id,
                    text=customer_message,
                    source="llm_handoff",
                    extra_payload={"handoff_reason": reason},
                )
                reply.handoff_reason = reason
                if self._turn_is_stale(is_turn_current):
                    return self._discard_model_turn_and_supersede(
                        session,
                        external_chat_id=external_chat_id,
                        turn_id=outbound_event_id,
                    )
                return reply

        return self._store_text_reply(
            session,
            external_chat_id=external_chat_id,
            outbound_event_id=outbound_event_id,
            text=PROVIDER_DELAY_TEXT,
            source="llm_round_limit",
        )

    @staticmethod
    def _prepare_tool_calls(tool_calls: list[ToolCall], *, round_index: int) -> list[ToolCall]:
        for index, call in enumerate(tool_calls, start=1):
            if not call.call_id:
                call.call_id = f"call_{round_index}_{index}_{call.name or 'unknown'}"
        return tool_calls

    def _execute_search_products(self, session, arguments: dict[str, Any]) -> dict[str, Any]:
        query_specs = self._normalize_query_specs(arguments.get("queries"))
        if not query_specs:
            return {
                "tool_name": "search_products",
                "status": "invalid_request",
                "message": "Не передано ни одного товара для поиска.",
                "result": {"query_order": [], "results": []},
            }

        results: list[dict[str, Any]] = []
        for spec in query_specs:
            item = search_products_structured(session, query=spec["query"])
            item["requested_quantity"] = spec.get("requested_quantity")
            item["requested_quantity_available"] = self._requested_quantity_available(
                item,
                spec.get("requested_quantity"),
            )
            results.append(item)

        payload = {
            "tool_name": "search_products",
            "status": "ok",
            "request": {"queries": query_specs},
            "result": {
                "query_order": [spec["query"] for spec in query_specs],
                "results": results,
            },
        }
        if self.debug_lookup_logs:
            logger.info("assistant_product_search payload=%s", json.dumps(payload, ensure_ascii=False))
        return payload

    @staticmethod
    def _normalize_query_specs(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []

        result: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                query = str(item.get("query") or "").strip()
                quantity = AssistantService._positive_number(item.get("requested_quantity"))
            else:
                query = str(item or "").strip()
                quantity = None
            if not query:
                continue
            spec: dict[str, Any] = {"query": query}
            if quantity is not None:
                spec["requested_quantity"] = quantity
            result.append(spec)
        return result

    @staticmethod
    def _positive_number(value: Any) -> int | float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            number = Decimal(str(value).replace(",", "."))
        except (InvalidOperation, ValueError):
            return None
        if not number.is_finite() or number <= 0:
            return None
        return int(number) if number == number.to_integral() else float(number)

    @staticmethod
    def _requested_quantity_available(item: dict, requested_quantity: int | float | None) -> bool | None:
        if requested_quantity is None:
            return None
        exact_matches = item.get("exact_matches") or []
        if len(exact_matches) != 1:
            return None
        stock_value = exact_matches[0].get("stock")
        if stock_value is None:
            return None
        try:
            return Decimal(str(stock_value)) >= Decimal(str(requested_quantity))
        except (InvalidOperation, ValueError):
            return None

    def _run_llm_messages(
        self,
        session,
        *,
        external_chat_id: str,
        outbound_event_id: str | None,
        request_id: str,
        messages: list[dict[str, Any]],
    ):
        turn = self.openai_service.run_messages(
            messages=messages,
            tools=OPENAI_TOOLS,
            tool_choice="auto",
        )
        self._record_llm_call(
            session,
            external_chat_id=external_chat_id,
            outbound_event_id=outbound_event_id,
            request_id=request_id,
            turn=turn,
        )
        # Usage must survive a later outbound Jivo failure.
        session.commit()
        return turn

    def _record_llm_call(
        self,
        session,
        *,
        external_chat_id: str,
        outbound_event_id: str | None,
        request_id: str,
        turn,
    ) -> None:
        usage = turn.usage or {}
        prompt_tokens = self._optional_int(usage.get("prompt_tokens"))
        completion_tokens = self._optional_int(usage.get("completion_tokens"))
        total_tokens = self._optional_int(usage.get("total_tokens"))
        thinking_tokens = None
        if total_tokens is not None:
            thinking_tokens = max(0, total_tokens - (prompt_tokens or 0) - (completion_tokens or 0))
        cost = turn.cost or {}
        create_llm_call(
            session,
            external_chat_id=external_chat_id,
            request_id=request_id,
            provider=self.openai_service.provider,
            model=self._active_llm_model(),
            purpose="model_driven",
            status=turn.error_type or "ok",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            thinking_tokens=thinking_tokens,
            total_tokens=total_tokens,
            latency_ms=turn.latency_ms,
            estimated_usd=cost.get("estimated_usd"),
            estimated_rub=cost.get("estimated_rub"),
            outbound_event_id=outbound_event_id,
        )

    def _append_assistant_tool_call_message(
        self,
        session,
        *,
        external_chat_id: str,
        tool_calls: list[ToolCall],
        content: str,
        turn_id: str | None,
    ) -> None:
        message = OpenAIService.build_assistant_tool_call_message(tool_calls)
        message["content"] = content
        append_message(
            session,
            external_chat_id=external_chat_id,
            sender_role="assistant_tool_call",
            text=content,
            payload={
                "source": "llm_tool_call",
                "turn_id": turn_id,
                "content": content,
                "tool_calls": message["tool_calls"],
            },
        )

    @staticmethod
    def _append_tool_result_message(
        session,
        *,
        external_chat_id: str,
        call: ToolCall,
        result: dict[str, Any],
        turn_id: str | None,
    ) -> None:
        message = OpenAIService.build_tool_result_message(
            tool_call_id=call.call_id,
            name=call.name,
            result=result,
        )
        append_message(
            session,
            external_chat_id=external_chat_id,
            sender_role="tool",
            text=message["content"],
            payload={
                "source": "tool_result",
                "turn_id": turn_id,
                "tool_name": call.name,
                "tool_call_id": call.call_id,
                "content": message["content"],
            },
        )

    def _store_text_reply(
        self,
        session,
        *,
        external_chat_id: str,
        outbound_event_id: str | None,
        text: str,
        source: str,
        extra_payload: dict[str, Any] | None = None,
    ) -> AssistantReply:
        payload = {"source": source, "turn_id": outbound_event_id}
        payload.update(extra_payload or {})
        append_message(
            session,
            external_chat_id=external_chat_id,
            sender_role="bot",
            text=text,
            external_event_id=outbound_event_id,
            payload=payload,
        )
        return AssistantReply(text=text)

    def _handoff_already_requested_reply(
        self,
        session,
        *,
        external_chat_id: str,
        outbound_event_id: str | None,
    ) -> AssistantReply:
        return self._store_text_reply(
            session,
            external_chat_id=external_chat_id,
            outbound_event_id=outbound_event_id,
            text=HANDOFF_ALREADY_REQUESTED_TEXT,
            source="handoff_already_requested",
        )

    @staticmethod
    def _collect_pending_client_messages(messages: list) -> list:
        pending = []
        for message in reversed(messages):
            if message.sender_role == "bot":
                break
            if message.sender_role == "client" and message.text.strip():
                pending.append(message)
        return list(reversed(pending))

    @staticmethod
    def _discard_model_turn_and_supersede(
        session,
        *,
        external_chat_id: str,
        turn_id: str | None,
    ) -> AssistantReply:
        session.rollback()
        if turn_id:
            for message in list_messages(session, external_chat_id):
                payload = message.payload or {}
                if message.external_event_id == turn_id or payload.get("turn_id") == turn_id:
                    session.delete(message)
            session.commit()
        return AssistantService._superseded_reply()

    @staticmethod
    def _turn_is_stale(is_turn_current) -> bool:
        return is_turn_current is not None and not is_turn_current()

    @staticmethod
    def _superseded_reply() -> AssistantReply:
        return AssistantReply(text="", superseded=True)

    def _active_llm_model(self) -> str | None:
        if self.openai_service.provider in {"google", "google_ai", "google_ai_studio", "gemini"}:
            return self.openai_service.google_ai_model
        if self.openai_service.provider in {"kaigo", "kaigo_codex", "codex_text"}:
            return self.openai_service.kaigo_model
        if self.openai_service.provider == "kie":
            return self.openai_service.kie_chat_model_path
        return self.openai_service.model

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _new_llm_request_id(external_chat_id: str, mode: str) -> str:
        safe_chat_id = re.sub(r"[^A-Za-z0-9_.:-]+", "_", external_chat_id)[:80]
        timestamp_us = int(datetime.now(UTC).timestamp() * 1_000_000)
        return f"{mode}:{safe_chat_id}:{timestamp_us}"

    @staticmethod
    def _summarize_tools(tools: list[dict]) -> list[dict[str, Any]]:
        return [
            {
                "name": (tool.get("function") or {}).get("name"),
                "parameters": (tool.get("function") or {}).get("parameters"),
            }
            for tool in tools
        ]

    def _log_llm_debug_event(self, stage: str, payload: dict[str, Any]) -> None:
        if not self.debug_llm_payloads:
            return
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "stage": stage,
            "provider": self.openai_service.provider,
            "model": self._active_llm_model(),
            "payload": payload,
        }
        try:
            self.debug_llm_payloads_path.parent.mkdir(parents=True, exist_ok=True)
            with self.debug_llm_payloads_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(event, ensure_ascii=False, default=str))
                file.write("\n")
        except Exception:  # pragma: no cover - diagnostics must not break replies
            logger.exception("Failed to write LLM debug payload")
