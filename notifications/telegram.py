import logging

import httpx


logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, settings) -> None:
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send_text(self, text: str) -> bool:
        if not self.enabled:
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text}

        try:
            response = httpx.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Failed to send Telegram notification")
            return False

        return True
