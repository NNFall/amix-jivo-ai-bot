import logging
import time

import httpx

from core.assistant_service import AssistantService
from database.db import create_db_and_tables, session_scope
from database.repositories import mark_chat_status, message_exists_by_external_event_id
from settings import get_settings


logger = logging.getLogger(__name__)


WELCOME_TEXT = (
    "Это демо-бот AMIX в Telegram. "
    "Я умею отвечать по артикулам, наличию, остаткам и ценам из базы. "
    "Если вопрос требует менеджера или технической консультации, я так и скажу."
)

HELP_TEXT = (
    "Отправьте артикул или вопрос по наличию. "
    "Команды: /start, /help, /reset."
)

RESET_TEXT = "История текущего демо-чата помечена как новая. Можете задать следующий вопрос."

TEXT_ONLY_TEXT = "Сейчас я работаю только с текстовыми сообщениями."


class TelegramDemoBot:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.token = self.settings.telegram_bot_token
        self.timeout = self.settings.telegram_demo_poll_timeout_seconds
        self.assistant_service = AssistantService()

        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required for Telegram demo bot")

        self.api_base = f"https://api.telegram.org/bot{self.token}"

    def run_forever(self) -> None:
        create_db_and_tables()
        offset: int | None = None
        logger.info("Telegram demo bot polling started")

        while True:
            try:
                updates = self._get_updates(offset)
                for update in updates:
                    offset = update["update_id"] + 1
                    self._handle_update(update)
            except KeyboardInterrupt:  # pragma: no cover - manual stop path
                logger.info("Telegram demo bot interrupted")
                raise
            except Exception:  # pragma: no cover - network/runtime safety path
                logger.exception("Telegram demo poll cycle failed")
                time.sleep(3)

    def _get_updates(self, offset: int | None) -> list[dict]:
        params = {
            "timeout": self.timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            params["offset"] = offset

        with httpx.Client(timeout=self.timeout + 10) as client:
            response = client.get(f"{self.api_base}/getUpdates", params=params)
            response.raise_for_status()
            payload = response.json()

        if not payload.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {payload}")

        return payload.get("result", [])

    def _handle_update(self, update: dict) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        from_user = message.get("from") or {}
        message_text = message.get("text")
        update_id = update["update_id"]
        inbound_event_id = f"telegram-update:{update_id}"

        with session_scope() as session:
            if message_exists_by_external_event_id(session, inbound_event_id):
                logger.info("Skipping duplicate Telegram update %s", update_id)
                return

        chat_id = str(chat.get("id") or "")
        user_id = str(from_user.get("id") or chat_id)
        external_chat_id = f"telegram:{chat_id}"
        external_client_id = f"telegram-user:{user_id}"
        customer_name = self._build_customer_name(from_user, chat)

        if not message_text:
            self._send_text(chat_id, TEXT_ONLY_TEXT)
            return

        normalized_text = message_text.strip()
        if normalized_text == "/start":
            self._send_text(chat_id, WELCOME_TEXT)
            return
        if normalized_text == "/help":
            self._send_text(chat_id, HELP_TEXT)
            return
        if normalized_text == "/reset":
            with session_scope() as session:
                mark_chat_status(session, external_chat_id, "active")
            self._send_text(chat_id, RESET_TEXT)
            return

        with session_scope() as session:
            assistant_reply = self.assistant_service.handle_client_message(
                session,
                external_chat_id=external_chat_id,
                external_client_id=external_client_id,
                customer_name=customer_name,
                customer_text=normalized_text,
                inbound_event_id=inbound_event_id,
                outbound_event_id=f"{inbound_event_id}:bot",
                payload={
                    "platform": "telegram",
                    "update_id": update_id,
                    "chat_id": chat_id,
                    "message_id": message.get("message_id"),
                },
                handoff_mode="demo",
            )

        self._send_text(chat_id, assistant_reply.text)

    def _send_text(self, chat_id: str, text: str) -> None:
        payload = {"chat_id": chat_id, "text": text}
        with httpx.Client(timeout=20) as client:
            response = client.post(f"{self.api_base}/sendMessage", json=payload)
            response.raise_for_status()

    @staticmethod
    def _build_customer_name(from_user: dict, chat: dict) -> str | None:
        first_name = (from_user.get("first_name") or "").strip()
        last_name = (from_user.get("last_name") or "").strip()
        full_name = " ".join(part for part in [first_name, last_name] if part).strip()
        if full_name:
            return full_name

        username = (from_user.get("username") or "").strip()
        if username:
            return f"@{username}"

        title = (chat.get("title") or "").strip()
        return title or None
