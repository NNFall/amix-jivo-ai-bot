import logging

from database.db import session_scope
from database.repositories import (
    append_message,
    delete_generated_messages_for_turn,
    get_chat_by_external_id,
    get_or_create_chat,
    get_or_create_customer,
    get_stored_event,
    log_processing_error,
    mark_chat_status,
    mark_event_failed,
    mark_event_processing,
    mark_event_processed,
    mark_event_superseded,
)
from jivo.client import JivoClient
from jivo.events import JivoEventType, get_terminal_chat_status, should_stop_bot_after_event
from jivo.schemas import JivoIncomingEvent
from notifications.telegram import TelegramNotifier
from settings import get_settings

from .assistant_service import AssistantService
from .handoff_service import HandoffService
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
        self.handoff_service = HandoffService()
        self.jivo_client = JivoClient(settings)
        self.telegram_notifier = TelegramNotifier(settings)

    def process_event_record(self, event_record_id: int) -> None:
        with session_scope() as session:
            event_record = get_stored_event(session, event_record_id)
            if event_record is None:
                logger.warning("Event record %s not found", event_record_id)
                return

            if event_record.status in {"processed", "superseded"}:
                logger.info("Event record %s was already processed", event_record_id)
                return

            event = JivoIncomingEvent.model_validate(event_record.payload)
            event_payload = dict(event_record.payload)
            mark_event_processing(session, event_record)

            try:
                deferred = self._handle_event(session, event, event_record_id=event_record.id)
            except Exception as exc:  # pragma: no cover - defensive branch
                logger.exception("Failed to process Jivo event %s", event.id)
                session.rollback()
                failed_event_record = get_stored_event(session, event_record_id)
                if failed_event_record is not None:
                    mark_event_failed(session, failed_event_record, str(exc))
                log_processing_error(session, event.id, "message_processor", str(exc), event_payload)
                if event.chat_id:
                    self.telegram_notifier.send_text(
                        f"[amix-jivo] Ошибка обработки события {event.id} в чате {event.chat_id}: {exc}"
                    )
                return

            if not deferred:
                mark_event_processed(session, event_record)

    def _handle_event(self, session, event: JivoIncomingEvent, *, event_record_id: int) -> bool:
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
            return False

        if event.event == JivoEventType.AGENT_UNAVAILABLE:
            mark_chat_status(session, chat.external_chat_id, "waiting_contact")
            GLOBAL_TURN_COORDINATOR.cancel(chat.external_chat_id)
            self._send_and_store_bot_reply(
                session,
                event=event,
                text=AGENT_UNAVAILABLE_TEXT,
            )
            return False

        if event.event != JivoEventType.CLIENT_MESSAGE:
            if chat.status not in {"agent_joined", "closed"}:
                mark_chat_status(session, chat.external_chat_id, "active")
            return False

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
            callback=lambda handle: self._process_pending_client_turn(
                handle=handle,
                event=event,
                event_record_id=event_record_id,
            ),
            on_superseded=lambda: self._finalize_event_record(
                event_record_id,
                status="superseded",
            ),
        )
        return True

    def _process_pending_client_turn(
        self,
        *,
        handle,
        event: JivoIncomingEvent,
        event_record_id: int | None = None,
    ) -> None:
        try:
            with session_scope() as session:
                self._run_pending_client_turn(
                    session,
                    handle=handle,
                    event=event,
                    event_record_id=event_record_id,
                )
        except Exception as exc:
            with session_scope() as session:
                chat = get_chat_by_external_id(session, event.chat_id)
                handoff_completed = bool(chat and chat.status == "handoff_requested")
                if not handoff_completed:
                    delete_generated_messages_for_turn(session, event.chat_id, f"{event.id}:bot")
                else:
                    delete_generated_messages_for_turn(
                        session, event.chat_id, f"{event.id}:bot", bot_only=True
                    )
                self._set_event_record_status(
                    session,
                    event_record_id,
                    status="processed" if handoff_completed else "failed",
                    error_text=str(exc),
                )
                log_processing_error(
                    session,
                    event.id,
                    "pending_client_turn",
                    str(exc),
                    event.model_dump(mode="json"),
                )
            raise

    def _run_pending_client_turn(
        self,
        session,
        *,
        handle,
        event: JivoIncomingEvent,
        event_record_id: int | None,
    ) -> None:
        assistant_reply = self.assistant_service.handle_pending_client_messages(
            session,
            external_chat_id=event.chat_id,
            outbound_event_id=f"{event.id}:bot",
            handoff_mode="jivo",
            is_turn_current=handle.is_current,
        )

        if assistant_reply.superseded or not assistant_reply.text:
            session.rollback()
            self._set_event_record_status(session, event_record_id, status="superseded")
            logger.info("Skipping superseded Jivo turn for chat %s", event.chat_id)
            return
        if not handle.is_current():
            session.rollback()
            self._set_event_record_status(session, event_record_id, status="superseded")
            logger.info("Skipping Jivo send for superseded chat %s", event.chat_id)
            return
        session.expire_all()
        chat = get_chat_by_external_id(session, event.chat_id)
        if chat is not None and chat.status in {"agent_joined", "closed"}:
            session.rollback()
            delete_generated_messages_for_turn(session, event.chat_id, f"{event.id}:bot")
            self._set_event_record_status(session, event_record_id, status="processed")
            logger.info(
                "Skipping Jivo invite/send for chat %s because status is %s",
                event.chat_id,
                chat.status,
            )
            return

        # Release the SQLite write transaction before outbound Jivo calls so
        # AGENT_JOINED/CHAT_CLOSED callbacks can be persisted concurrently.
        session.commit()
        if assistant_reply.handoff_reason:
            try:
                invited = self.jivo_client.invite_agent(
                    event=event,
                    reason=assistant_reply.handoff_reason,
                )
                if not invited:
                    raise RuntimeError("Jivo manager invite was not accepted")
            except Exception:
                delete_generated_messages_for_turn(session, event.chat_id, f"{event.id}:bot")
                session.expire_all()
                chat = get_chat_by_external_id(session, event.chat_id)
                if chat is not None and chat.status not in {"agent_joined", "closed"}:
                    mark_chat_status(session, event.chat_id, "active")
                session.commit()
                logger.exception(
                    "phase=invite_agent_failed_before_send chat_id=%s event_id=%s action=invite_agent",
                    event.chat_id,
                    event.id,
                )
                raise

            self.handoff_service.register_handoff(
                session,
                event.chat_id,
                assistant_reply.handoff_reason,
            )
            session.commit()
            if not handle.is_current():
                self._set_event_record_status(session, event_record_id, status="processed")
                logger.info("Skipping stale Jivo handoff message for chat %s", event.chat_id)
                return
            session.expire_all()
            chat = get_chat_by_external_id(session, event.chat_id)
            if chat is not None and chat.status in {"agent_joined", "closed"}:
                self._set_event_record_status(session, event_record_id, status="processed")
                logger.info(
                    "Skipping Jivo handoff message for chat %s because status is %s",
                    event.chat_id,
                    chat.status,
                )
                return
        delivered = self._deliver_bot_reply(
            session,
            event=event,
            text=assistant_reply.text,
            is_turn_current=handle.is_current,
        )
        if not delivered:
            delete_generated_messages_for_turn(session, event.chat_id, f"{event.id}:bot")
            session.expire_all()
            chat = get_chat_by_external_id(session, event.chat_id)
            status = "processed" if chat and chat.status in {"agent_joined", "closed"} else "superseded"
            self._set_event_record_status(session, event_record_id, status=status)
            return
        self._set_event_record_status(session, event_record_id, status="processed")

    @staticmethod
    def _set_event_record_status(
        session,
        event_record_id: int | None,
        *,
        status: str,
        error_text: str | None = None,
    ) -> None:
        if event_record_id is None:
            return
        event_record = get_stored_event(session, event_record_id)
        if event_record is None:
            return
        if status == "processed":
            mark_event_processed(session, event_record)
            event_record.error_text = error_text
        elif status == "superseded":
            mark_event_superseded(session, event_record)
        elif status == "failed":
            mark_event_failed(session, event_record, error_text or "Background turn failed")

    def _finalize_event_record(self, event_record_id: int, *, status: str) -> None:
        with session_scope() as session:
            self._set_event_record_status(session, event_record_id, status=status)

    def _deliver_bot_reply(
        self,
        session,
        event: JivoIncomingEvent,
        text: str,
        is_turn_current=None,
    ) -> bool:
        if should_stop_bot_after_event(event.event):
            return False
        if is_turn_current is not None and not is_turn_current():
            logger.info("Skipping bot reply for superseded chat %s at delivery boundary", event.chat_id)
            return False

        session.expire_all()
        chat = get_chat_by_external_id(session, event.chat_id)
        if chat is not None and chat.status in {"agent_joined", "closed"}:
            logger.info("Skipping bot reply for chat %s because status is %s", event.chat_id, chat.status)
            return False

        logger.info(
            "phase=message_send_started chat_id=%s event_id=%s text_length=%s",
            event.chat_id,
            event.id,
            len(text or ""),
        )
        try:
            if is_turn_current is not None and not is_turn_current():
                logger.info("Skipping bot reply for superseded chat %s before outbound call", event.chat_id)
                return False
            sent = self.jivo_client.send_text_message(event=event, text=text)
            if not sent:
                raise RuntimeError("Jivo bot message was not accepted")
        except Exception:
            logger.exception("phase=message_send_failed chat_id=%s event_id=%s", event.chat_id, event.id)
            raise
        logger.info(
            "phase=message_sent_to_user chat_id=%s event_id=%s text_length=%s",
            event.chat_id,
            event.id,
            len(text or ""),
        )
        return True

    def _send_and_store_bot_reply(self, session, event: JivoIncomingEvent, text: str) -> None:
        if not self._deliver_bot_reply(session, event=event, text=text):
            return
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
