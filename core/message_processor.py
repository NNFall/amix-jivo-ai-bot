import logging

from database.db import session_scope
from database.repositories import (
    append_message,
    get_chat_by_external_id,
    get_or_create_chat,
    get_or_create_customer,
    get_product_by_article,
    get_similar_products,
    get_stored_event,
    log_processing_error,
    mark_chat_status,
    mark_event_failed,
    mark_event_processing,
    mark_event_processed,
)
from jivo.client import JivoClient
from jivo.events import JivoEventType, get_terminal_chat_status, should_stop_bot_after_event
from jivo.schemas import JivoIncomingEvent
from llm.openai_client import OpenAIService
from notifications.telegram import TelegramNotifier
from products.article_utils import extract_article_candidates
from products.product_search import ProductSearchService
from settings import get_settings

from .dialog_service import DialogService
from .handoff_service import HandoffService


logger = logging.getLogger(__name__)


SAFE_FALLBACK_TEXT = (
    "Я могу помочь с артикулами, наличием, остатками и ценами. "
    "Если пришлёте артикул, я проверю базу. "
    "Если нужен подбор или техническая консультация, я передам вопрос менеджеру."
)

AGENT_UNAVAILABLE_TEXT = (
    "Сейчас менеджер недоступен. Можете оставить телефон или e-mail, "
    "и коллеги свяжутся с вами позже."
)


class MessageProcessor:
    def __init__(self) -> None:
        settings = get_settings()
        self.dialog_service = DialogService(history_limit=settings.history_limit)
        self.handoff_service = HandoffService()
        self.jivo_client = JivoClient(settings)
        self.openai_service = OpenAIService(settings)
        self.product_search = ProductSearchService()
        self.telegram_notifier = TelegramNotifier(settings)

    def process_event_record(self, event_record_id: int) -> None:
        with session_scope() as session:
            event_record = get_stored_event(session, event_record_id)
            if event_record is None:
                logger.warning("Event record %s not found", event_record_id)
                return

            if event_record.status == "processed":
                logger.info("Event record %s was already processed", event_record_id)
                return

            event = JivoIncomingEvent.model_validate(event_record.payload)
            mark_event_processing(session, event_record)

            try:
                self._handle_event(session, event)
            except Exception as exc:  # pragma: no cover - defensive branch
                logger.exception("Failed to process Jivo event %s", event.id)
                mark_event_failed(session, event_record, str(exc))
                log_processing_error(session, event.id, "message_processor", str(exc), event_record.payload)
                if event.chat_id:
                    self.telegram_notifier.send_text(
                        f"[amix-jivo] Ошибка обработки события {event.id} в чате {event.chat_id}: {exc}"
                    )
                return

            mark_event_processed(session, event_record)

    def _handle_event(self, session, event: JivoIncomingEvent) -> None:
        customer = get_or_create_customer(
            session,
            external_client_id=event.client_id,
            name=event.sender.name if event.sender else None,
        )
        chat = get_or_create_chat(session, event.chat_id, customer.id)

        if should_stop_bot_after_event(event.event):
            terminal_status = get_terminal_chat_status(event.event) or "closed"
            mark_chat_status(session, chat.external_chat_id, terminal_status)
            return

        if event.event == JivoEventType.AGENT_UNAVAILABLE:
            mark_chat_status(session, chat.external_chat_id, "waiting_contact")
            self._send_bot_reply(
                session,
                event=event,
                text=AGENT_UNAVAILABLE_TEXT,
            )
            return

        if event.event != JivoEventType.CLIENT_MESSAGE:
            mark_chat_status(session, chat.external_chat_id, "active")
            return

        client_text = event.message.text if event.message else ""
        append_message(
            session,
            external_chat_id=chat.external_chat_id,
            sender_role="client",
            text=client_text,
            external_event_id=event.id,
            payload=event.model_dump(mode="json"),
        )

        handoff_decision = self.handoff_service.evaluate(client_text)
        if handoff_decision.should_handoff and handoff_decision.reason:
            self._handoff_to_agent(session, event, reason=handoff_decision.reason)
            return

        article_candidates = extract_article_candidates(client_text)
        for candidate in article_candidates:
            product = get_product_by_article(session, candidate)
            if product is not None:
                reply = self.product_search.build_product_reply(product)
                self._send_bot_reply(session, event=event, text=reply)
                return

        if article_candidates:
            similar_products = get_similar_products(session, article_candidates[0], limit=5)
            if similar_products:
                reply = self.product_search.build_similar_products_reply(article_candidates[0], similar_products)
                self._send_bot_reply(session, event=event, text=reply)
                return

        transcript = self.dialog_service.get_transcript(session, chat.external_chat_id)
        llm_reply = self.openai_service.generate_reply(
            customer_text=client_text,
            transcript=transcript,
        )
        self._send_bot_reply(session, event=event, text=llm_reply or SAFE_FALLBACK_TEXT)

    def _handoff_to_agent(self, session, event: JivoIncomingEvent, reason: str) -> None:
        self.handoff_service.register_handoff(session, event.chat_id, reason)
        notice = "Передаю ваш вопрос менеджеру."
        self._send_bot_reply(session, event=event, text=notice)
        self.jivo_client.invite_agent(event=event, reason=reason)

    def _send_bot_reply(self, session, event: JivoIncomingEvent, text: str) -> None:
        if should_stop_bot_after_event(event.event):
            return

        chat = get_chat_by_external_id(session, event.chat_id)
        if chat is not None and chat.status in {"agent_joined", "closed"}:
            logger.info("Skipping bot reply for chat %s because status is %s", event.chat_id, chat.status)
            return

        self.jivo_client.send_text_message(event=event, text=text)
        append_message(
            session,
            external_chat_id=event.chat_id,
            sender_role="bot",
            text=text,
            external_event_id=f"{event.id}:bot",
            payload={"event": JivoEventType.BOT_MESSAGE, "text": text},
        )


def process_event_record(event_record_id: int) -> None:
    MessageProcessor().process_event_record(event_record_id)
