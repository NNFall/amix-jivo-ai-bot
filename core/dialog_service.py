from database.repositories import list_messages


class DialogService:
    """Expose the complete stored dialog in provider-compatible role order."""

    def get_transcript(self, session, external_chat_id: str) -> str:
        lines: list[str] = []
        for message in list_messages(session, external_chat_id):
            if message.sender_role not in {"client", "bot"} or not message.text:
                continue
            speaker = "Клиент" if message.sender_role == "client" else "Бот"
            lines.append(f"{speaker}: {message.text}")
        return "\n".join(lines)

    def get_llm_messages(self, session, external_chat_id: str) -> list[dict]:
        result: list[dict] = []
        for message in list_messages(session, external_chat_id):
            converted = self._to_llm_message(message)
            if converted is not None:
                result.append(converted)
        return result

    @staticmethod
    def _to_llm_message(message) -> dict | None:
        payload = message.payload or {}
        if message.sender_role == "client" and message.text:
            return {"role": "user", "content": message.text}
        if message.sender_role == "bot" and message.text:
            return {"role": "assistant", "content": message.text}
        if message.sender_role == "assistant_tool_call":
            tool_calls = payload.get("tool_calls") or []
            if tool_calls:
                return {
                    "role": "assistant",
                    "content": payload.get("content") or message.text or "",
                    "tool_calls": tool_calls,
                }
        if message.sender_role == "tool":
            content = message.text or payload.get("content")
            if content:
                converted = {"role": "tool", "content": content}
                if payload.get("tool_call_id"):
                    converted["tool_call_id"] = payload["tool_call_id"]
                if payload.get("tool_name"):
                    converted["name"] = payload["tool_name"]
                return converted
        return None
