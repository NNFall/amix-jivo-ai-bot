from database.repositories import list_recent_messages


class DialogService:
    def __init__(self, history_limit: int = 20) -> None:
        self.history_limit = history_limit

    def get_transcript(self, session, external_chat_id: str) -> str:
        messages = list_recent_messages(session, external_chat_id, limit=self.history_limit)
        lines: list[str] = []

        for message in messages:
            speaker = "Клиент" if message.sender_role == "client" else "Бот"
            if not message.text:
                continue
            lines.append(f"{speaker}: {message.text}")

        return "\n".join(lines)
