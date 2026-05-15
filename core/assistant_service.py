from dataclasses import dataclass

from database.repositories import (
    append_message,
    get_or_create_chat,
    get_or_create_customer,
    get_product_by_article,
    get_similar_products,
)
from llm.openai_client import OpenAIService
from products.article_utils import extract_article_candidates
from products.product_search import ProductSearchService
from settings import get_settings

from .dialog_service import DialogService
from .handoff_service import HandoffService


SAFE_FALLBACK_TEXT = (
    "Я могу помочь с артикулами, наличием, остатками и ценами. "
    "Если пришлете артикул, я проверю базу. "
    "Если нужен подбор или техническая консультация, я передам вопрос менеджеру."
)

JIVO_HANDOFF_TEXT = "Передаю ваш вопрос менеджеру."

TELEGRAM_DEMO_HANDOFF_TEXT = (
    "Этот вопрос требует менеджера. В рабочем режиме я бы передал диалог оператору. "
    "В демо-режиме могу продолжить только по артикулам, наличию, остаткам и ценам."
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

        handoff_decision = self.handoff_service.evaluate(customer_text)
        if handoff_decision.should_handoff and handoff_decision.reason:
            self.handoff_service.register_handoff(session, chat.external_chat_id, handoff_decision.reason)
            handoff_text = self._resolve_handoff_text(handoff_mode)
            self._append_bot_message(
                session,
                external_chat_id=chat.external_chat_id,
                text=handoff_text,
                outbound_event_id=outbound_event_id,
                payload={"handoff_reason": handoff_decision.reason},
            )
            return AssistantReply(text=handoff_text, handoff_reason=handoff_decision.reason)

        article_candidates = extract_article_candidates(customer_text)
        for candidate in article_candidates:
            product = get_product_by_article(session, candidate)
            if product is not None:
                reply_text = self.product_search.build_product_reply(product)
                self._append_bot_message(
                    session,
                    external_chat_id=chat.external_chat_id,
                    text=reply_text,
                    outbound_event_id=outbound_event_id,
                    payload={"matched_article": candidate},
                )
                return AssistantReply(text=reply_text)

        if article_candidates:
            similar_products = get_similar_products(session, article_candidates[0], limit=5)
            if similar_products:
                reply_text = self.product_search.build_similar_products_reply(article_candidates[0], similar_products)
                self._append_bot_message(
                    session,
                    external_chat_id=chat.external_chat_id,
                    text=reply_text,
                    outbound_event_id=outbound_event_id,
                    payload={"similar_for": article_candidates[0]},
                )
                return AssistantReply(text=reply_text)

        transcript = self.dialog_service.get_transcript(session, chat.external_chat_id)
        llm_reply = self.openai_service.generate_reply(
            customer_text=customer_text,
            transcript=transcript,
        )
        reply_text = llm_reply or SAFE_FALLBACK_TEXT
        self._append_bot_message(
            session,
            external_chat_id=chat.external_chat_id,
            text=reply_text,
            outbound_event_id=outbound_event_id,
            payload={"source": "llm" if llm_reply else "fallback"},
        )
        return AssistantReply(text=reply_text)

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
