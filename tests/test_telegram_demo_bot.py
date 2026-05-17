from database.db import session_scope
from database.models import Chat, Handoff, Message
from database.repositories import append_message, create_handoff, get_or_create_chat, get_or_create_customer, reset_chat_context
from notifications.telegram_demo_bot import BOT_COMMANDS, TelegramDemoBot


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
