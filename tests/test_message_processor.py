import pytest

from core.assistant_service import AssistantReply
from core.message_processor import MessageProcessor
from database.db import session_scope
from database.repositories import get_or_create_chat, get_or_create_customer, mark_chat_status
from jivo.schemas import JivoIncomingEvent


class _CurrentHandle:
    @staticmethod
    def is_current() -> bool:
        return True


class _MutableHandle:
    def __init__(self) -> None:
        self.current = True

    def is_current(self) -> bool:
        return self.current


class _Assistant:
    @staticmethod
    def handle_pending_client_messages(*args, **kwargs) -> AssistantReply:
        return AssistantReply(text="Передаю вопрос менеджеру.", handoff_reason="client_requested_manager")


class _OperatorJoinedAssistant:
    @staticmethod
    def handle_pending_client_messages(session, *, external_chat_id: str, **kwargs) -> AssistantReply:
        mark_chat_status(session, external_chat_id, "agent_joined")
        session.flush()
        return AssistantReply(text="Передаю вопрос менеджеру.", handoff_reason="client_requested_manager")


class _Jivo:
    def __init__(self, calls: list[str], *, fail_invite: bool = False, invite_result: bool = True) -> None:
        self.calls = calls
        self.fail_invite = fail_invite
        self.invite_result = invite_result

    def invite_agent(self, **kwargs) -> bool:
        self.calls.append("invite")
        if self.fail_invite:
            raise RuntimeError("invite failed")
        return self.invite_result


class _TurnCancelledDuringInviteJivo(_Jivo):
    def __init__(self, calls: list[str], handle: _MutableHandle) -> None:
        super().__init__(calls)
        self.handle = handle

    def invite_agent(self, **kwargs) -> bool:
        result = super().invite_agent(**kwargs)
        self.handle.current = False
        return result


def _processor(
    calls: list[str], *, fail_invite: bool = False, invite_result: bool = True
) -> MessageProcessor:
    processor = object.__new__(MessageProcessor)
    processor.assistant_service = _Assistant()
    processor.jivo_client = _Jivo(calls, fail_invite=fail_invite, invite_result=invite_result)
    processor._deliver_bot_reply = lambda *args, **kwargs: calls.append("send")
    return processor


def _event() -> JivoIncomingEvent:
    return JivoIncomingEvent(
        id="handoff-event",
        event="CLIENT_MESSAGE",
        chat_id="handoff-chat",
        client_id="handoff-client",
        message={"type": "TEXT", "text": "Позовите менеджера"},
    )


def _create_chat() -> None:
    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="handoff-client")
        get_or_create_chat(session, "handoff-chat", customer.id)


def test_manager_invite_happens_before_handoff_message(isolated_app_env) -> None:
    _create_chat()
    calls: list[str] = []

    _processor(calls)._process_pending_client_turn(handle=_CurrentHandle(), event=_event())

    assert calls == ["invite", "send"]


def test_failed_manager_invite_does_not_send_false_handoff_promise(isolated_app_env) -> None:
    _create_chat()
    calls: list[str] = []

    with pytest.raises(RuntimeError, match="invite failed"):
        _processor(calls, fail_invite=True)._process_pending_client_turn(handle=_CurrentHandle(), event=_event())

    assert calls == ["invite"]


def test_rejected_manager_invite_does_not_send_false_handoff_promise(isolated_app_env) -> None:
    _create_chat()
    calls: list[str] = []

    with pytest.raises(RuntimeError, match="invite was not accepted"):
        _processor(calls, invite_result=False)._process_pending_client_turn(
            handle=_CurrentHandle(), event=_event()
        )

    assert calls == ["invite"]


def test_operator_joined_while_model_was_running_prevents_invite_and_send(isolated_app_env) -> None:
    _create_chat()
    calls: list[str] = []
    processor = _processor(calls)
    processor.assistant_service = _OperatorJoinedAssistant()

    processor._process_pending_client_turn(handle=_CurrentHandle(), event=_event())

    assert calls == []


def test_operator_joined_during_invite_prevents_handoff_message(isolated_app_env) -> None:
    _create_chat()
    calls: list[str] = []
    handle = _MutableHandle()
    processor = _processor(calls)
    processor.jivo_client = _TurnCancelledDuringInviteJivo(calls, handle)

    processor._process_pending_client_turn(handle=handle, event=_event())

    assert calls == ["invite"]
