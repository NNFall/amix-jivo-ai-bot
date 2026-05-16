from dataclasses import dataclass
from decimal import Decimal
import logging

from database.repositories import (
    append_message,
    get_or_create_chat,
    get_or_create_customer,
    get_product_by_article,
    get_similar_products,
    lookup_products,
)
from llm.openai_client import OpenAIService
from llm.prompts import FACTS_RESPONSE_SYSTEM_PROMPT, build_facts_response_prompt
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


@dataclass(slots=True)
class LookupPlan:
    mode: str
    lookup_query: str = ""
    direct_response: str = ""
    clarify_text: str = ""
    handoff_reason: str = ""


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
            return self._handle_via_llm(
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

    def _handle_via_llm(
        self,
        session,
        *,
        external_chat_id: str,
        customer_text: str,
        outbound_event_id: str | None,
        handoff_mode: str,
    ) -> AssistantReply:
        transcript = self.dialog_service.get_transcript(session, external_chat_id)
        plan_payload = self.openai_service.generate_lookup_plan(customer_text=customer_text, transcript=transcript)
        plan = self._parse_plan(plan_payload, customer_text)
        self._log_plan(customer_text=customer_text, plan_payload=plan_payload, parsed_plan=plan)

        if (
            plan.mode == "handoff"
            and not self._is_explicit_manager_request(customer_text)
            and self._is_price_stock_request(customer_text)
            and self._has_lookup_candidate(customer_text)
        ):
            forced_query = plan.lookup_query or self._first_lookup_candidate(customer_text)
            plan = LookupPlan(
                mode="lookup",
                lookup_query=forced_query,
                handoff_reason=plan.handoff_reason,
            )
            self._log_forced_lookup_override(customer_text=customer_text, lookup_query=forced_query)

        if plan.mode == "respond":
            direct_response = plan.direct_response or self.openai_service.generate_reply(
                customer_text=customer_text,
                transcript=transcript,
            )
            reply_text = direct_response or SAFE_FALLBACK_TEXT
            self._append_bot_message(
                session,
                external_chat_id=external_chat_id,
                text=reply_text,
                outbound_event_id=outbound_event_id,
                payload={"source": "llm_direct"},
            )
            return AssistantReply(text=reply_text)

        if plan.mode == "handoff":
            reason = plan.handoff_reason or "llm_requested_manager"
            self.handoff_service.register_handoff(session, external_chat_id, reason)
            handoff_text = self._resolve_handoff_text(handoff_mode)
            self._append_bot_message(
                session,
                external_chat_id=external_chat_id,
                text=handoff_text,
                outbound_event_id=outbound_event_id,
                payload={"handoff_reason": reason, "source": "llm_plan"},
            )
            return AssistantReply(text=handoff_text, handoff_reason=reason)

        if plan.mode == "clarify":
            clarify_text = plan.clarify_text or ARTICLE_REQUIRED_TEXT
            self._append_bot_message(
                session,
                external_chat_id=external_chat_id,
                text=clarify_text,
                outbound_event_id=outbound_event_id,
                payload={"source": "llm_plan", "mode": "clarify"},
            )
            return AssistantReply(text=clarify_text)

        lookup_query = plan.lookup_query or self._first_lookup_candidate(customer_text)
        if not lookup_query:
            self._append_bot_message(
                session,
                external_chat_id=external_chat_id,
                text=ARTICLE_REQUIRED_TEXT,
                outbound_event_id=outbound_event_id,
                payload={"source": "llm_plan", "mode": "empty_lookup"},
            )
            return AssistantReply(text=ARTICLE_REQUIRED_TEXT)

        exact_matches, similar_matches = lookup_products(session, lookup_query)
        self._log_lookup_call(lookup_query=lookup_query, exact_matches=exact_matches, similar_matches=similar_matches)

        facts_prompt = build_facts_response_prompt(
            customer_text=customer_text,
            transcript=transcript,
            lookup_query=lookup_query,
            exact_matches=[self._serialize_product(product) for product in exact_matches],
            similar_matches=[self._serialize_product(product) for product in similar_matches[:10]],
        )
        llm_reply = self.openai_service.generate_text(
            system_prompt=FACTS_RESPONSE_SYSTEM_PROMPT,
            user_prompt=facts_prompt,
        )

        if not llm_reply:
            llm_reply = self._build_programmatic_lookup_fallback(
                lookup_query=lookup_query,
                exact_matches=exact_matches,
                similar_matches=similar_matches,
            )

        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=llm_reply,
            outbound_event_id=outbound_event_id,
            payload={
                "source": "llm_facts",
                "lookup_query": lookup_query,
                "exact_count": len(exact_matches),
                "similar_count": len(similar_matches),
            },
        )
        return AssistantReply(text=llm_reply)

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
            self.handoff_service.register_handoff(session, external_chat_id, handoff_decision.reason)
            handoff_text = self._resolve_handoff_text(handoff_mode)
            self._append_bot_message(
                session,
                external_chat_id=external_chat_id,
                text=handoff_text,
                outbound_event_id=outbound_event_id,
                payload={"handoff_reason": handoff_decision.reason, "source": "legacy"},
            )
            return AssistantReply(text=handoff_text, handoff_reason=handoff_decision.reason)

        article_candidates = extract_article_candidates(customer_text)
        if not article_candidates and self._needs_article_lookup(customer_text):
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

        transcript = self.dialog_service.get_transcript(session, external_chat_id)
        llm_reply = self.openai_service.generate_reply(
            customer_text=customer_text,
            transcript=transcript,
        )
        reply_text = llm_reply or SAFE_FALLBACK_TEXT
        self._append_bot_message(
            session,
            external_chat_id=external_chat_id,
            text=reply_text,
            outbound_event_id=outbound_event_id,
            payload={"source": "legacy_llm" if llm_reply else "legacy_fallback"},
        )
        return AssistantReply(text=reply_text)

    @staticmethod
    def _parse_plan(plan_payload: dict | None, customer_text: str) -> LookupPlan:
        if not isinstance(plan_payload, dict):
            return LookupPlan(mode="respond")

        mode_raw = str(plan_payload.get("mode", "")).strip().lower()
        if mode_raw not in {"respond", "lookup", "clarify", "handoff"}:
            mode_raw = "respond"

        lookup_query = str(plan_payload.get("lookup_query", "")).strip()
        direct_response = str(plan_payload.get("direct_response", "")).strip()
        clarify_text = str(plan_payload.get("clarify_text", "")).strip()
        handoff_reason = str(plan_payload.get("handoff_reason", "")).strip()

        if "менеджер" in customer_text.lower() and mode_raw != "handoff":
            mode_raw = "handoff"
            handoff_reason = handoff_reason or "client_requested_manager"

        return LookupPlan(
            mode=mode_raw,
            lookup_query=lookup_query,
            direct_response=direct_response,
            clarify_text=clarify_text,
            handoff_reason=handoff_reason,
        )

    @staticmethod
    def _is_explicit_manager_request(customer_text: str) -> bool:
        text = customer_text.lower()
        keywords = ("менеджер", "оператор", "человек", "перезвон", "позвон")
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _is_price_stock_request(customer_text: str) -> bool:
        text = customer_text.lower()
        keywords = ("цен", "стоит", "стоим", "налич", "остат", "сколько")
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _has_lookup_candidate(customer_text: str) -> bool:
        return bool(AssistantService._first_lookup_candidate(customer_text))

    @staticmethod
    def _first_lookup_candidate(customer_text: str) -> str:
        candidates = extract_article_candidates(customer_text)
        return candidates[0] if candidates else ""

    def _log_plan(self, *, customer_text: str, plan_payload: dict | None, parsed_plan: LookupPlan) -> None:
        if not self.debug_lookup_logs:
            return
        logger.info(
            "assistant_lookup_plan customer_text=%r raw=%s parsed_mode=%s parsed_lookup_query=%r parsed_handoff_reason=%r",
            customer_text,
            plan_payload,
            parsed_plan.mode,
            parsed_plan.lookup_query,
            parsed_plan.handoff_reason,
        )

    def _log_forced_lookup_override(self, *, customer_text: str, lookup_query: str) -> None:
        if not self.debug_lookup_logs:
            return
        logger.info(
            "assistant_lookup_plan_override reason=price_stock_with_candidate customer_text=%r forced_lookup_query=%r",
            customer_text,
            lookup_query,
        )

    def _log_lookup_call(self, *, lookup_query: str, exact_matches: list, similar_matches: list) -> None:
        if not self.debug_lookup_logs:
            return
        exact_preview = [{"code": product.code, "article": product.article} for product in exact_matches[:5]]
        similar_preview = [{"code": product.code, "article": product.article} for product in similar_matches[:5]]
        logger.info(
            "assistant_lookup_call query=%r exact_count=%d similar_count=%d exact_preview=%s similar_preview=%s",
            lookup_query,
            len(exact_matches),
            len(similar_matches),
            exact_preview,
            similar_preview,
        )

    @staticmethod
    def _build_programmatic_lookup_fallback(
        *,
        lookup_query: str,
        exact_matches: list,
        similar_matches: list,
    ) -> str:
        if len(exact_matches) == 1:
            return ProductSearchService().build_product_reply(exact_matches[0])

        if len(exact_matches) > 1:
            prices = [product.retail_price for product in exact_matches if isinstance(product.retail_price, Decimal)]
            price_span = ""
            if prices:
                values = sorted(prices)
                low = values[0]
                high = values[-1]
                price_span = f" Цена: {low} руб." if low == high else f" Цена от {low} до {high} руб."

            code_list = ", ".join((product.code or "-") for product in exact_matches[:6])
            return (
                f"По запросу {lookup_query} найдено несколько вариантов: {code_list}."
                f"{price_span} Уточните, пожалуйста, какой код вы видите на сайте."
            )

        if similar_matches:
            return ProductSearchService().build_similar_products_reply(lookup_query, similar_matches[:5])

        return (
            f"Не нашёл точные данные по запросу {lookup_query}. "
            "Уточните, пожалуйста, артикул или код, и я проверю ещё раз."
        )

    @staticmethod
    def _serialize_product(product) -> dict:
        return {
            "code": product.code,
            "article": product.article,
            "retail_price": AssistantService._decimal_to_float(product.retail_price),
            "corporate_price": AssistantService._decimal_to_float(product.corporate_price),
            "free_stock": AssistantService._decimal_to_float(product.free_stock),
            "unit": product.unit,
            "weight": AssistantService._decimal_to_float(product.weight),
            "volume": AssistantService._decimal_to_float(product.volume),
        }

    @staticmethod
    def _decimal_to_float(value: Decimal | None) -> float | None:
        return float(value) if value is not None else None

    @staticmethod
    def _resolve_handoff_text(handoff_mode: str) -> str:
        if handoff_mode == "demo":
            return TELEGRAM_DEMO_HANDOFF_TEXT
        return JIVO_HANDOFF_TEXT

    @staticmethod
    def _needs_article_lookup(customer_text: str) -> bool:
        text = customer_text.lower()
        keywords = (
            "артикул",
            "код",
            "налич",
            "остат",
            "цен",
            "стоит",
            "сколько",
            "в наличии",
        )
        return any(keyword in text for keyword in keywords)

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
