from enum import StrEnum


class JivoEventType(StrEnum):
    CLIENT_MESSAGE = "CLIENT_MESSAGE"
    BOT_MESSAGE = "BOT_MESSAGE"
    INVITE_AGENT = "INVITE_AGENT"
    AGENT_JOINED = "AGENT_JOINED"
    AGENT_UNAVAILABLE = "AGENT_UNAVAILABLE"
    CHAT_CLOSED = "CHAT_CLOSED"


TERMINAL_EVENT_STATUSES = {
    JivoEventType.AGENT_JOINED: "agent_joined",
    JivoEventType.CHAT_CLOSED: "closed",
}


def should_stop_bot_after_event(event_name: str) -> bool:
    return event_name in TERMINAL_EVENT_STATUSES


def get_terminal_chat_status(event_name: str) -> str | None:
    return TERMINAL_EVENT_STATUSES.get(event_name)
