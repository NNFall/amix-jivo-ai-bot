import json
import re

from database.repositories import list_messages


class DialogService:
    def get_transcript(self, session, external_chat_id: str) -> str:
        messages = list_messages(session, external_chat_id)
        lines: list[str] = []

        for message in messages:
            if message.sender_role not in {"client", "bot"}:
                continue
            speaker = "Клиент" if message.sender_role == "client" else "Бот"
            if not message.text:
                continue
            lines.append(f"{speaker}: {message.text}")

        return "\n".join(lines)

    def get_llm_messages(self, session, external_chat_id: str) -> list[dict]:
        messages = list_messages(session, external_chat_id)
        result: list[dict] = []

        for message in messages:
            role_message = self._to_llm_message(message)
            if role_message:
                result.append(role_message)

        return result

    @classmethod
    def _to_llm_message(cls, message) -> dict | None:
        payload = message.payload or {}
        sender_role = message.sender_role

        if sender_role == "client":
            if not message.text:
                return None
            return {"role": "user", "content": message.text}

        if sender_role == "bot":
            if not message.text:
                return None
            return {"role": "assistant", "content": cls._hide_exact_stock_in_text(message.text)}

        if sender_role == "assistant_tool_call":
            tool_calls = payload.get("tool_calls") or []
            if not tool_calls:
                return None
            return {"role": "assistant", "content": payload.get("content") or "", "tool_calls": tool_calls}

        if sender_role == "tool":
            content = message.text or payload.get("content")
            if not content:
                return None
            if payload.get("tool_name") == "search_products":
                content = cls._hide_exact_stock(content)
            role_message = {"role": "tool", "content": content}
            if payload.get("tool_call_id"):
                role_message["tool_call_id"] = payload["tool_call_id"]
            if payload.get("tool_name"):
                role_message["name"] = payload["tool_name"]
            return role_message

        return None

    @classmethod
    def _hide_exact_stock(cls, content: str) -> str:
        try:
            payload = json.loads(content)
        except (TypeError, ValueError):
            return content
        return json.dumps(cls._without_exact_stock(payload), ensure_ascii=False)

    @classmethod
    def _without_exact_stock(cls, value):
        if isinstance(value, list):
            return [cls._without_exact_stock(item) for item in value]
        if not isinstance(value, dict):
            return value

        result = {}
        for key, item in value.items():
            normalized_key = str(key).lower().replace("_", "").replace("-", "").replace(" ", "")
            if normalized_key in {
                "stock",
                "stockdisplay",
                "freestock",
                "остаток",
                "свободныйостаток",
            }:
                continue
            result[key] = cls._without_exact_stock(item)
        return result

    @staticmethod
    def _hide_exact_stock_in_text(content: str) -> str:
        patterns = (
            r"(?:в наличии|на складе|остат(?:ок|ке)|доступно)[^\n.!?]{0,40}?\d+(?:[.,]\d+)?\s*(?:шт|штук|компл|ед|упак)\.?",
            r"\d+(?:[.,]\d+)?\s*(?:шт|штук|компл|ед|упак)\.?[^\n.!?]{0,25}?(?:в наличии|на складе|в остатке)",
        )
        sanitized = content
        for pattern in patterns:
            sanitized = re.sub(pattern, "[точный остаток скрыт]", sanitized, flags=re.IGNORECASE)
        return sanitized
