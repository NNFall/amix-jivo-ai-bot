from enum import StrEnum


class JivoEventType(StrEnum):
    CLIENT_MESSAGE = "CLIENT_MESSAGE"
    BOT_MESSAGE = "BOT_MESSAGE"
    INVITE_AGENT = "INVITE_AGENT"
    AGENT_JOINED = "AGENT_JOINED"
    AGENT_UNAVAILABLE = "AGENT_UNAVAILABLE"
    CHAT_CLOSED = "CHAT_CLOSED"


TERMINAL_EVENTS = {
    JivoEventType.AGENT_JOINED,
    JivoEventType.CHAT_CLOSED,
}


def should_stop_bot_after_event(event_name: str) -> bool:
    return event_name in TERMINAL_EVENTS
