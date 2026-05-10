import logging
from time import time
from uuid import uuid4

import httpx

from jivo.events import JivoEventType


logger = logging.getLogger(__name__)


class JivoClient:
    def __init__(self, settings) -> None:
        self.endpoint = settings.jivo_bot_api_url
        self.timeout = settings.jivo_api_timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)

    def send_text_message(self, event, text: str) -> bool:
        payload = {
            "id": str(uuid4()),
            "event": JivoEventType.BOT_MESSAGE,
            "chat_id": event.chat_id,
            "client_id": event.client_id,
            "message": {
                "type": "TEXT",
                "text": text,
                "timestamp": int(time()),
            },
        }
        return self._post(payload)

    def invite_agent(self, event, reason: str) -> bool:
        payload = {
            "id": str(uuid4()),
            "event": JivoEventType.INVITE_AGENT,
            "chat_id": event.chat_id,
            "client_id": event.client_id,
            "reason": reason,
        }
        return self._post(payload)

    def _post(self, payload: dict) -> bool:
        if not self.enabled:
            logger.warning("Jivo outbound endpoint is not configured; skipping payload %s", payload["event"])
            return False

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(self.endpoint, json=payload)
                response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Failed to send payload to Jivo")
            return False

        return True
