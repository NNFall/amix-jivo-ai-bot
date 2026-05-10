from dataclasses import dataclass

from database.repositories import create_handoff, mark_chat_status


MANAGER_KEYWORDS = (
    "менеджер",
    "оператор",
    "человек",
    "позвон",
    "перезвон",
    "телефон",
    "заказ",
    "оформить",
)

COMPLEX_KEYWORDS = (
    "аналог",
    "совместим",
    "совместимость",
    "подойдет",
    "подойдёт",
    "отлич",
    "разница",
    "сравн",
    "какой выбрать",
    "что выбрать",
    "подбор",
    "глубин",
)


@dataclass(slots=True)
class HandoffDecision:
    should_handoff: bool
    reason: str | None = None


class HandoffService:
    def evaluate(self, customer_text: str) -> HandoffDecision:
        text = customer_text.lower()

        if any(keyword in text for keyword in MANAGER_KEYWORDS):
            return HandoffDecision(True, "client_requested_manager")

        if any(keyword in text for keyword in COMPLEX_KEYWORDS):
            return HandoffDecision(True, "complex_technical_question")

        return HandoffDecision(False, None)

    def register_handoff(self, session, external_chat_id: str, reason: str) -> None:
        mark_chat_status(session, external_chat_id, "handoff_requested")
        create_handoff(session, external_chat_id, reason=reason)
