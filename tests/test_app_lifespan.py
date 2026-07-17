from fastapi.testclient import TestClient

import main
from database.db import session_scope
from database.models import JivoEvent
from main import create_application
from settings import get_settings


def test_lifespan_starts_remote_xml_auto_import_when_enabled(
    isolated_app_env,
    monkeypatch,
) -> None:
    events: list[str] = []

    class FakeRunner:
        def __init__(self, *args, **kwargs) -> None:
            events.append("created")

        async def start(self) -> None:
            events.append("started")

        async def stop(self) -> None:
            events.append("stopped")

    monkeypatch.setenv("PRODUCTS_XML_AUTO_IMPORT_ENABLED", "true")
    monkeypatch.setenv("PRODUCTS_XML_REMOTE_URL", "https://example.test/prices.xml")
    get_settings.cache_clear()
    monkeypatch.setattr(main, "ProductsXmlAutoImportRunner", FakeRunner)

    with TestClient(create_application()):
        assert events == ["created", "started"]

    assert events == ["created", "started", "stopped"]


def test_lifespan_recovers_unfinished_jivo_events(isolated_app_env, monkeypatch) -> None:
    with session_scope() as session:
        for index, status in enumerate(("received", "processing", "processed"), start=1):
            session.add(
                JivoEvent(
                    external_event_id=f"recovery-{index}",
                    external_chat_id="recovery-chat",
                    external_client_id="recovery-client",
                    event_type="CLIENT_MESSAGE",
                    status=status,
                    payload={
                        "id": f"recovery-{index}",
                        "event": "CLIENT_MESSAGE",
                        "chat_id": "recovery-chat",
                        "client_id": "recovery-client",
                        "message": {"type": "TEXT", "text": "test"},
                    },
                )
            )

    recovered: list[int] = []
    monkeypatch.setattr(main, "process_event_record", recovered.append)

    with TestClient(create_application()):
        pass

    assert len(recovered) == 2
