from fastapi.testclient import TestClient

import main
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
