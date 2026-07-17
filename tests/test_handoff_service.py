from core.handoff_service import HandoffService
from database.db import session_scope
from database.models import Handoff
from database.repositories import get_or_create_chat, get_or_create_customer


def test_handoff_service_only_persists_model_decision(isolated_app_env) -> None:
    service = HandoffService()
    assert not hasattr(service, "evaluate")

    with session_scope() as session:
        customer = get_or_create_customer(session, external_client_id="customer:handoff-service")
        chat = get_or_create_chat(session, "chat:handoff-service", customer.id)
        service.register_handoff(session, chat.external_chat_id, "technical_consultation")

        assert chat.status == "handoff_requested"
        handoff = session.query(Handoff).one()

    assert handoff.reason == "technical_consultation"
