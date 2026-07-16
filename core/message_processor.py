import logging

from database.db import session_scope
from database.repositories import (
    append_message,
    get_chat_by_external_id,
    get_or_create_chat,
    get_or_create_customer,
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
from notifications.telegram import TelegramNotifier
from settings import get_settings

from .assistant_service import AssistantService
from .turn_coordinator import GLOBAL_TURN_COORDINATOR


logger = logging.getLogger(__name__)


AGENT_UNAVAILABLE_TEXT = (
    "Сейчас менеджер недоступен. Можете оставить телефон или e-mail, "
    "и коллеги свяжутся с вами позже."
)


class MessageProcessor:
    def __init__(self) -> None:
        settings = get_settings()
        self.turn_debounce_seconds = settings.turn_debounce_seconds
        self.assistant_service = AssistantService()
        self.jivo_client = JivoClient(settings)
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
            GLOBAL_TURN_COORDINATOR.cancel(chat.external_chat_id)
            return

        if event.event == JivoEventType.AGENT_UNAVAILABLE:
            mark_chat_status(session, chat.external_chat_id, "waiting_contact")
            self._send_and_store_bot_reply(
                session,
                event=event,
                text=AGENT_UNAVAILABLE_TEXT,
            )
            return

        if event.event != JivoEventType.CLIENT_MESSAGE:
            if chat.status not in {"agent_joined", "closed"}:
                mark_chat_status(session, chat.external_chat_id, "active")
            return

        client_text = event.message.text if event.message else ""
        self.assistant_service.record_client_message(
            session,
            external_chat_id=chat.external_chat_id,
            external_client_id=event.client_id,
            customer_name=event.sender.name if event.sender else None,
            customer_text=client_text,
            inbound_event_id=event.id,
            payload=event.model_dump(mode="json"),
        )
        GLOBAL_TURN_COORDINATOR.submit(
            chat_id=chat.external_chat_id,
            delay_seconds=max(self.turn_debounce_seconds, 0.05),
            callback=lambda handle: self._process_pending_client_turn(handle=handle, event=event),
        )

    def _process_pending_client_turn(self, *, handle, event: JivoIncomingEvent) -> None:
        with session_scope() as session:
            assistant_reply = self.assistant_service.handle_pending_client_messages(
                session,
                external_chat_id=event.chat_id,
                outbound_event_id=f"{event.id}:bot",
                handoff_mode="jivo",
                is_turn_current=handle.is_current,
            )

            if assistant_reply.superseded or not assistant_reply.text:
                logger.info("Skipping superseded Jivo turn for chat %s", event.chat_id)
                return
            if not handle.is_current():
                logger.info("Skipping Jivo send for superseded chat %s", event.chat_id)
                return
            session.expire_all()
            chat = get_chat_by_external_id(session, event.chat_id)
            if chat is not None and chat.status in {"agent_joined", "closed"}:
                logger.info(
                    "Skipping Jivo invite/send for chat %s because status is %s",
                    event.chat_id,
                    chat.status,
                )
                return

            if assistant_reply.handoff_reason:
                try:
                    invited = self.jivo_client.invite_agent(
                        event=event,
                        reason=assistant_reply.handoff_reason,
                    )
                    if not invited:
                        raise RuntimeError("Jivo manager invite was not accepted")
                except Exception:
                    logger.exception(
                        "phase=invite_agent_failed_before_send chat_id=%s event_id=%s action=invite_agent",
                        event.chat_id,
                        event.id,
                    )
                    raise
                if not handle.is_current():
                    logger.info("Skipping Jivo handoff message because operator joined chat %s", event.chat_id)
                    return
                session.expire_all()
                chat = get_chat_by_external_id(session, event.chat_id)
                if chat is not None and chat.status in {"agent_joined", "closed"}:
                    logger.info(
                        "Skipping Jivo handoff message for chat %s because status is %s",
                        event.chat_id,
                        chat.status,
                    )
                    return
            self._deliver_bot_reply(session, event=event, text=assistant_reply.text)

    def _deliver_bot_reply(self, session, event: JivoIncomingEvent, text: str) -> None:
        if should_stop_bot_after_event(event.event):
            return

        chat = get_chat_by_external_id(session, event.chat_id)
        if chat is not None and chat.status in {"agent_joined", "closed"}:
            logger.info("Skipping bot reply for chat %s because status is %s", event.chat_id, chat.status)
            return

        logger.info(
            "phase=message_send_started chat_id=%s event_id=%s text_length=%s",
            event.chat_id,
            event.id,
            len(text or ""),
        )
        try:
            self.jivo_client.send_text_message(event=event, text=text)
        except Exception:
            logger.exception("phase=message_send_failed chat_id=%s event_id=%s", event.chat_id, event.id)
            raise
        logger.info(
            "phase=message_sent_to_user chat_id=%s event_id=%s text_length=%s",
            event.chat_id,
            event.id,
            len(text or ""),
        )

    def _send_and_store_bot_reply(self, session, event: JivoIncomingEvent, text: str) -> None:
        self._deliver_bot_reply(session, event=event, text=text)
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
