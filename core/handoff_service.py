from database.repositories import create_handoff, mark_chat_status


class HandoffService:
    """Persist a handoff already selected by the language model."""

    def register_handoff(self, session, external_chat_id: str, reason: str) -> None:
        mark_chat_status(session, external_chat_id, "handoff_requested")
        create_handoff(session, external_chat_id, reason=reason)
