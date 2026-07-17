from database.repositories import create_handoff, mark_chat_handoff_requested_if_not_terminal


class HandoffService:
    """Persist a handoff already selected by the language model."""

    def register_handoff(self, session, external_chat_id: str, reason: str) -> None:
        mark_chat_handoff_requested_if_not_terminal(session, external_chat_id)
        create_handoff(session, external_chat_id, reason=reason)
