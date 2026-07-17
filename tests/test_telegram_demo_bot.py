import pytest

from core.assistant_service import AssistantReply
from database.db import session_scope
from database.models import Chat, Handoff, Message
from database.repositories import append_message, create_handoff, get_or_create_chat, get_or_create_customer, reset_chat_context
from notifications.telegram_demo_bot import BOT_COMMANDS, TelegramDemoBot


class _StaleHandle:
    @staticmethod
    def is_current() -> bool:
        return False


class _CurrentHandle:
    @staticmethod
    def is_current() -> bool:
        return True


class _PersistingTelegramAssistant:
    @staticmethod
    def handle_pending_client_messages(
        session,
        *,
        external_chat_id: str,
        outbound_event_id: str,
        **kwargs,
    ) -> AssistantReply:
        append_message(
            session,
            external_chat_id=external_chat_id,
            sender_role="bot",
            text="Reply",
            external_event_id=outbound_event_id,
            payload={"turn_id": outbound_event_id},
        )
        return AssistantReply(text="Reply")


def test_telegram_demo_has_single_context_reset_command() -> None:
    command_names = [item["command"] for item in BOT_COMMANDS]

    assert command_names == ["start", "help", "newchat"]
    assert TelegramDemoBot._command_name("/newchat") == "newchat"  # noqa: SLF001
    assert TelegramDemoBot._command_name("/newchat@testdemoNN_bot") == "newchat"  # noqa: SLF001
    assert TelegramDemoBot._command_name("/clear") == "clear"  # noqa: SLF001
    assert TelegramDemoBot._command_name("new chat") is None  # noqa: SLF001


def test_reset_chat_context_removes_messages_and_handoffs(isolated_app_env) -> None:
    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="telegram-user:1", name="User")
        chat = get_or_create_chat(session, external_chat_id="telegram:1", customer_id=customer.id)
        chat.status = "handoff_requested"
        append_message(session, external_chat_id="telegram:1", sender_role="client", text="есть мп 28ск")
        append_message(session, external_chat_id="telegram:1", sender_role="bot", text="уточните цену")
        create_handoff(session, external_chat_id="telegram:1", reason="test")

        deleted_count = reset_chat_context(session, "telegram:1")

        assert deleted_count == 2
        assert session.query(Message).count() == 0
        assert session.query(Handoff).count() == 0
        assert session.query(Chat).filter(Chat.external_chat_id == "telegram:1").one().status == "active"


def test_stale_telegram_turn_discards_unsent_generated_history(isolated_app_env) -> None:
    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="telegram-user:stale")
        get_or_create_chat(session, external_chat_id="telegram:stale", customer_id=customer.id)

    bot = object.__new__(TelegramDemoBot)
    bot.assistant_service = _PersistingTelegramAssistant()
    bot._send_text = lambda *args, **kwargs: pytest.fail("stale reply must not be sent")

    bot._process_pending_turn(
        handle=_StaleHandle(),
        chat_id="stale",
        external_chat_id="telegram:stale",
        outbound_event_id="telegram-stale:bot",
    )

    with session_scope() as session:
        assert session.query(Message).count() == 0


def test_failed_telegram_send_discards_generated_history(isolated_app_env) -> None:
    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="telegram-user:failed")
        get_or_create_chat(session, external_chat_id="telegram:failed", customer_id=customer.id)

    bot = object.__new__(TelegramDemoBot)
    bot.assistant_service = _PersistingTelegramAssistant()

    def fail_send(*args, **kwargs):
        raise RuntimeError("telegram send failed")

    bot._send_text = fail_send
    with pytest.raises(RuntimeError, match="telegram send failed"):
        bot._process_pending_turn(
            handle=_CurrentHandle(),
            chat_id="failed",
            external_chat_id="telegram:failed",
            outbound_event_id="telegram-failed:bot",
        )

    with session_scope() as session:
        assert session.query(Message).count() == 0
