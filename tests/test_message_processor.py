import pytest

from core.assistant_service import AssistantReply, AssistantService
from core.handoff_service import HandoffService
from core.message_processor import MessageProcessor
from database.db import session_scope
from database.models import Chat, Customer, Handoff, JivoEvent, Message, ProcessingError
from database.repositories import append_message, get_or_create_chat, get_or_create_customer, mark_chat_status
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


class _SequencedHandle:
    def __init__(self, values: list[bool]) -> None:
        self.values = iter(values)

    def is_current(self) -> bool:
        return next(self.values)


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


class _PersistingAssistant:
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
            sender_role="assistant_tool_call",
            text="",
            payload={"turn_id": outbound_event_id, "tool_calls": []},
        )
        append_message(
            session,
            external_chat_id=external_chat_id,
            sender_role="tool",
            text="{}",
            payload={"turn_id": outbound_event_id, "tool_name": "handoff_to_manager"},
        )
        append_message(
            session,
            external_chat_id=external_chat_id,
            sender_role="bot",
            text="Передаю вопрос менеджеру.",
            external_event_id=outbound_event_id,
            payload={"turn_id": outbound_event_id},
        )
        return AssistantReply(text="Передаю вопрос менеджеру.", handoff_reason="client_requested_manager")


class _StalePersistingAssistant:
    def __init__(self, handle: _MutableHandle) -> None:
        self.handle = handle

    def handle_pending_client_messages(
        self,
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
            text="Устаревший ответ",
            external_event_id=outbound_event_id,
            payload={"turn_id": outbound_event_id},
        )
        self.handle.current = False
        return AssistantReply(text="Устаревший ответ")


class _PersistingTextAssistant:
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


class _AgentJoinedDuringInviteJivo(_Jivo):
    def invite_agent(self, **kwargs) -> bool:
        result = super().invite_agent(**kwargs)
        with session_scope() as session:
            mark_chat_status(session, "handoff-chat", "agent_joined")
        return result


class _InviteAcceptedSendRejectedJivo(_Jivo):
    def send_text_message(self, **kwargs) -> bool:
        self.calls.append("send")
        return False


class _RejectingSendJivo(_Jivo):
    def send_text_message(self, **kwargs) -> bool:
        self.calls.append("send")
        return False


class _AcceptingSendJivo(_Jivo):
    def send_text_message(self, **kwargs) -> bool:
        self.calls.append("send")
        return True


class _ReplyingAssistant:
    @staticmethod
    def record_client_message(session, **kwargs) -> str:
        return AssistantService.record_client_message(_ReplyingAssistant(), session, **kwargs)

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
            text="Ответ",
            external_event_id=outbound_event_id,
            payload={"turn_id": outbound_event_id},
        )
        return AssistantReply(text="Ответ")


class _BrokenTransactionAssistant:
    @staticmethod
    def record_client_message(session, **kwargs) -> str:
        session.add(Customer(external_client_id="handoff-client"))
        session.flush()
        return "handoff-chat"


class _CapturingCoordinator:
    def __init__(self) -> None:
        self.callback = None
        self.on_superseded = None

    def submit(self, *, callback, on_superseded=None, **kwargs):
        self.callback = callback
        self.on_superseded = on_superseded

    @staticmethod
    def cancel(*args, **kwargs) -> None:
        return None


class _Notifier:
    @staticmethod
    def send_text(*args, **kwargs) -> bool:
        return True


def _processor(
    calls: list[str], *, fail_invite: bool = False, invite_result: bool = True
) -> MessageProcessor:
    processor = object.__new__(MessageProcessor)
    processor.assistant_service = _Assistant()
    processor.handoff_service = HandoffService()
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


def _create_event_record() -> int:
    event = _event()
    with session_scope() as session:
        record = JivoEvent(
            external_event_id=event.id,
            external_chat_id=event.chat_id,
            external_client_id=event.client_id,
            event_type=event.event,
            payload=event.model_dump(mode="json"),
        )
        session.add(record)
        session.flush()
        return record.id


def _deferred_processor(calls: list[str], *, accept_send: bool) -> MessageProcessor:
    processor = object.__new__(MessageProcessor)
    processor.turn_debounce_seconds = 0
    processor.assistant_service = _ReplyingAssistant()
    processor.handoff_service = HandoffService()
    processor.jivo_client = _AcceptingSendJivo(calls) if accept_send else _RejectingSendJivo(calls)
    processor.telegram_notifier = _Notifier()
    return processor


def test_client_event_is_completed_only_after_jivo_delivery(
    isolated_app_env,
    monkeypatch,
) -> None:
    event_record_id = _create_event_record()
    coordinator = _CapturingCoordinator()
    monkeypatch.setattr("core.message_processor.GLOBAL_TURN_COORDINATOR", coordinator)
    processor = _deferred_processor([], accept_send=True)

    processor.process_event_record(event_record_id)

    with session_scope() as session:
        assert session.get(JivoEvent, event_record_id).status == "processing"

    coordinator.callback(_CurrentHandle())

    with session_scope() as session:
        assert session.get(JivoEvent, event_record_id).status == "processed"


def test_failed_jivo_delivery_marks_event_failed_and_discards_generated_turn(
    isolated_app_env,
    monkeypatch,
) -> None:
    event_record_id = _create_event_record()
    coordinator = _CapturingCoordinator()
    monkeypatch.setattr("core.message_processor.GLOBAL_TURN_COORDINATOR", coordinator)
    processor = _deferred_processor([], accept_send=False)

    processor.process_event_record(event_record_id)
    with pytest.raises(RuntimeError, match="message was not accepted"):
        coordinator.callback(_CurrentHandle())

    with session_scope() as session:
        event = session.get(JivoEvent, event_record_id)
        assert event.status == "failed"
        assert event.error_text
        assert [message.sender_role for message in session.query(Message).all()] == ["client"]


def test_debounced_client_event_is_marked_superseded_without_generating_a_reply(
    isolated_app_env,
    monkeypatch,
) -> None:
    event_record_id = _create_event_record()
    coordinator = _CapturingCoordinator()
    monkeypatch.setattr("core.message_processor.GLOBAL_TURN_COORDINATOR", coordinator)
    processor = _deferred_processor([], accept_send=True)

    processor.process_event_record(event_record_id)
    coordinator.on_superseded()

    with session_scope() as session:
        assert session.get(JivoEvent, event_record_id).status == "superseded"
        assert [message.sender_role for message in session.query(Message).all()] == ["client"]


def test_database_failure_is_recorded_after_transaction_rollback(isolated_app_env) -> None:
    _create_chat()
    event_record_id = _create_event_record()
    processor = _deferred_processor([], accept_send=True)
    processor.assistant_service = _BrokenTransactionAssistant()

    processor.process_event_record(event_record_id)

    with session_scope() as session:
        event = session.get(JivoEvent, event_record_id)
        assert event.status == "failed"
        assert event.error_text
        assert session.query(ProcessingError).count() == 1


def test_manager_invite_happens_before_handoff_message(isolated_app_env) -> None:
    _create_chat()
    calls: list[str] = []

    _processor(calls)._process_pending_client_turn(handle=_CurrentHandle(), event=_event())

    assert calls == ["invite", "send"]
    with session_scope() as session:
        assert session.query(Handoff).count() == 1
        assert session.query(Chat).one().status == "handoff_requested"


def test_failed_manager_invite_does_not_send_false_handoff_promise(isolated_app_env) -> None:
    _create_chat()
    calls: list[str] = []

    with pytest.raises(RuntimeError, match="invite failed"):
        _processor(calls, fail_invite=True)._process_pending_client_turn(handle=_CurrentHandle(), event=_event())

    assert calls == ["invite"]
    with session_scope() as session:
        assert session.query(Handoff).count() == 0
        assert session.query(Chat).one().status == "active"


def test_failed_manager_invite_discards_generated_turn_history(isolated_app_env) -> None:
    _create_chat()
    calls: list[str] = []
    processor = _processor(calls, fail_invite=True)
    processor.assistant_service = _PersistingAssistant()

    with pytest.raises(RuntimeError, match="invite failed"):
        processor._process_pending_client_turn(handle=_CurrentHandle(), event=_event())

    with session_scope() as session:
        assert session.query(Message).count() == 0
        assert session.query(Chat).one().status == "active"


def test_turn_that_becomes_stale_after_generation_is_rolled_back(isolated_app_env) -> None:
    _create_chat()
    calls: list[str] = []
    handle = _MutableHandle()
    processor = _processor(calls)
    processor.assistant_service = _StalePersistingAssistant(handle)

    processor._process_pending_client_turn(handle=handle, event=_event())

    assert calls == []
    with session_scope() as session:
        assert session.query(Message).count() == 0


def test_turn_cancelled_at_delivery_boundary_discards_unsent_generated_history(
    isolated_app_env,
) -> None:
    _create_chat()
    calls: list[str] = []
    processor = _processor(calls)
    processor.assistant_service = _PersistingTextAssistant()
    processor._deliver_bot_reply = MessageProcessor._deliver_bot_reply.__get__(processor)
    handle = _SequencedHandle([True, False])

    processor._process_pending_client_turn(handle=handle, event=_event())

    assert calls == []
    with session_scope() as session:
        assert session.query(Message).count() == 0


def test_rejected_manager_invite_does_not_send_false_handoff_promise(isolated_app_env) -> None:
    _create_chat()
    calls: list[str] = []

    with pytest.raises(RuntimeError, match="invite was not accepted"):
        _processor(calls, invite_result=False)._process_pending_client_turn(
            handle=_CurrentHandle(), event=_event()
        )

    assert calls == ["invite"]
    with session_scope() as session:
        assert session.query(Handoff).count() == 0
        assert session.query(Chat).one().status == "active"


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


def test_operator_joined_during_invite_remains_terminal(isolated_app_env) -> None:
    _create_chat()
    calls: list[str] = []
    processor = _processor(calls)
    processor.jivo_client = _AgentJoinedDuringInviteJivo(calls)
    processor._deliver_bot_reply = MessageProcessor._deliver_bot_reply.__get__(processor)

    processor._process_pending_client_turn(handle=_CurrentHandle(), event=_event())

    assert calls == ["invite"]
    with session_scope() as session:
        assert session.query(Chat).one().status == "agent_joined"
        assert session.query(Handoff).count() == 1


def test_successful_invite_with_failed_message_keeps_handoff_but_not_unsent_bot_text(
    isolated_app_env,
) -> None:
    _create_chat()
    event_record_id = _create_event_record()
    calls: list[str] = []
    processor = _processor(calls)
    processor.assistant_service = _PersistingAssistant()
    processor.jivo_client = _InviteAcceptedSendRejectedJivo(calls)
    processor._deliver_bot_reply = MessageProcessor._deliver_bot_reply.__get__(processor)

    with pytest.raises(RuntimeError, match="message was not accepted"):
        processor._process_pending_client_turn(
            handle=_CurrentHandle(),
            event=_event(),
            event_record_id=event_record_id,
        )

    assert calls == ["invite", "send"]
    with session_scope() as session:
        assert session.query(Chat).one().status == "handoff_requested"
        assert session.query(Handoff).count() == 1
        event = session.get(JivoEvent, event_record_id)
        assert event.status == "processed"
        assert "message was not accepted" in event.error_text
        assert [message.sender_role for message in session.query(Message).all()] == [
            "assistant_tool_call",
            "tool",
        ]


def test_rejected_jivo_message_send_is_reported_as_failure(isolated_app_env) -> None:
    _create_chat()
    calls: list[str] = []
    processor = object.__new__(MessageProcessor)
    processor.jivo_client = _RejectingSendJivo(calls)

    with session_scope() as session:
        with pytest.raises(RuntimeError, match="message was not accepted"):
            processor._deliver_bot_reply(session, event=_event(), text="Ответ")

    assert calls == ["send"]


def test_stale_turn_is_checked_inside_delivery_boundary(isolated_app_env) -> None:
    _create_chat()
    calls: list[str] = []
    processor = object.__new__(MessageProcessor)
    processor.jivo_client = _RejectingSendJivo(calls)

    with session_scope() as session:
        processor._deliver_bot_reply(
            session,
            event=_event(),
            text="Устаревший ответ",
            is_turn_current=lambda: False,
        )

    assert calls == []
