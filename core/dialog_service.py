from database.repositories import list_messages


class DialogService:
    def __init__(self, history_limit: int = 20) -> None:
        self.history_limit = history_limit

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

    @staticmethod
    def _to_llm_message(message) -> dict | None:
        payload = message.payload or {}
        sender_role = message.sender_role

        if sender_role == "client":
            if not message.text:
                return None
            return {"role": "user", "content": message.text}

        if sender_role == "bot":
            if not message.text:
                return None
            return {"role": "assistant", "content": message.text}

        if sender_role == "assistant_tool_call":
            tool_calls = payload.get("tool_calls") or []
            if not tool_calls:
                return None
            return {"role": "assistant", "content": payload.get("content") or "", "tool_calls": tool_calls}

        if sender_role == "tool":
            content = message.text or payload.get("content")
            if not content:
                return None
            role_message = {"role": "tool", "content": content}
            if payload.get("tool_call_id"):
                role_message["tool_call_id"] = payload["tool_call_id"]
            if payload.get("tool_name"):
                role_message["name"] = payload["tool_name"]
            return role_message

        return None
