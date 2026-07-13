from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from database.db import session_scope
from database.models import Chat, Customer, LLMCall, Product, ProductImport
from main import create_application
from products.remote_xml_importer import RemoteXmlImportResult
from products.xml_importer import XmlImportResult
from settings import get_settings


def build_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    get_settings.cache_clear()
    return TestClient(create_application())


def test_admin_page_redirects_to_login_without_session(isolated_app_env, monkeypatch) -> None:
    with build_client(monkeypatch) as client:
        response = client.get("/admin", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_admin_login_page_shows_password_form(isolated_app_env, monkeypatch) -> None:
    with build_client(monkeypatch) as client:
        response = client.get("/admin/login")

    assert response.status_code == 200
    assert "Вход в панель" in response.text
    assert 'name="password"' in response.text
    assert "Войти" in response.text
    assert "WWW-Authenticate" not in response.headers


def test_admin_login_sets_cookie_and_allows_page_access(isolated_app_env, monkeypatch) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="770",
                article="14.023пр.",
                normalized_article="14023ПР",
                free_stock=220,
                unit="шт",
                retail_price=473,
                raw_payload={},
            )
        )
        session.add(
            ProductImport(
                filename="products.xml",
                source_path="data/incoming_xml/products.xml",
                status="completed",
                imported_count=1,
                updated_count=0,
                error_count=0,
                created_at=datetime(2026, 5, 31, 12, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 31, 12, 1, tzinfo=UTC),
            )
        )

    with build_client(monkeypatch) as client:
        login_response = client.post(
            "/admin/login",
            data={"password": "secret"},
            follow_redirects=False,
        )
        page_response = client.get("/admin")

    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/admin"
    assert "amix_admin_session" in login_response.headers["set-cookie"]
    assert page_response.status_code == 200
    assert "AMIX AI бот" in page_response.text
    assert "Товаров в базе" in page_response.text
    assert "Токенов LLM" in page_response.text
    assert "Расход LLM" in page_response.text
    assert "Скачать текущую базу" in page_response.text
    assert "Выберите файл или перенесите сюда" in page_response.text


def test_admin_login_rejects_wrong_password_without_browser_basic_prompt(
    isolated_app_env,
    monkeypatch,
) -> None:
    with build_client(monkeypatch) as client:
        response = client.post("/admin/login", data={"password": "wrong"})

    assert response.status_code == 200
    assert "Неверный пароль" in response.text


def test_admin_page_shows_cumulative_llm_usage(isolated_app_env, monkeypatch) -> None:
    with session_scope() as session:
        customer = Customer(external_client_id="admin-stats-customer")
        session.add(customer)
        session.flush()
        chat = Chat(external_chat_id="admin-stats-chat", customer_id=customer.id)
        session.add(chat)
        session.flush()
        session.add(
            LLMCall(
                chat_id=chat.id,
                request_id="admin-stats-call",
                provider="google_ai_studio",
                model="gemini-3.1-flash-lite",
                purpose="direct",
                status="ok",
                prompt_tokens=1000,
                completion_tokens=100,
                thinking_tokens=100,
                total_tokens=1200,
                latency_ms=1234,
                estimated_usd=Decimal("0.00055"),
                estimated_rub=Decimal("0.055"),
            )
        )

    with build_client(monkeypatch) as client:
        client.post("/admin/login", data={"password": "secret"})
        response = client.get("/admin")

    assert "1 200" in response.text
    assert "1 запрос" in response.text
    assert "0.06 ₽" in response.text
    assert "amix_admin_session" not in response.headers.get("set-cookie", "")
    assert "WWW-Authenticate" not in response.headers


def test_admin_downloads_current_products_as_xml_after_login(isolated_app_env, monkeypatch) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="770",
                article="14.023пр.",
                normalized_article="14023ПР",
                free_stock=220,
                unit="шт",
                retail_price=473,
                corporate_price=350,
                weight="0.070",
                raw_payload={},
            )
        )

    with build_client(monkeypatch) as client:
        client.post("/admin/login", data={"password": "secret"})
        response = client.get("/admin/products.xml")

    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "<Код>770</Код>" in response.text
    assert "<Артикул>14.023пр.</Артикул>" in response.text
    assert "<СвободныйОстаток>220.000</СвободныйОстаток>" in response.text


def test_admin_uploads_xml_and_imports_products_after_login(isolated_app_env, monkeypatch) -> None:
    xml_payload = """<?xml version="1.0" encoding="utf-8"?>
<root>
  <record>
    <Код>22608</Код>
    <Артикул>P-AM02/B-S</Артикул>
    <ЦенаРозничная>1024.00</ЦенаРозничная>
    <ЕдиницаИзмерения>шт</ЕдиницаИзмерения>
    <СвободныйОстаток>7.00</СвободныйОстаток>
  </record>
</root>
"""

    with build_client(monkeypatch) as client:
        client.post("/admin/login", data={"password": "secret"})
        response = client.post(
            "/admin/products/import",
            files={"file": ("products.xml", xml_payload.encode("utf-8"), "application/xml")},
            follow_redirects=False,
        )

    assert response.status_code == 303
    with session_scope() as session:
        product = session.query(Product).filter(Product.code == "22608").one()

    assert product.article == "P-AM02/B-S"
    assert str(product.free_stock) == "7.000"


def test_admin_runs_remote_xml_import_after_login(isolated_app_env, monkeypatch, tmp_path) -> None:
    class FakeRemoteImporter:
        def __init__(self, *args, **kwargs) -> None:
            pass

        @classmethod
        def from_settings(cls, settings):
            assert settings.products_xml_remote_url == "https://example.test/prices.xml"
            return cls()

        def download_and_import(self) -> RemoteXmlImportResult:
            with session_scope() as session:
                session.add(
                    Product(
                        code="770",
                        article="14.023пр.",
                        normalized_article="14023ПР",
                        free_stock=220,
                        unit="шт",
                        retail_price=473,
                        raw_payload={},
                    )
                )
            return RemoteXmlImportResult(
                status="completed",
                source_url="https://example.test/prices.xml",
                saved_path=tmp_path / "remote.xml",
                downloaded_bytes=123,
                import_result=XmlImportResult(status="completed", processed=1, created=1),
            )

    monkeypatch.setenv("PRODUCTS_XML_REMOTE_URL", "https://example.test/prices.xml")
    monkeypatch.setattr("api.admin.ProductRemoteXmlImporter", FakeRemoteImporter)

    with build_client(monkeypatch) as client:
        client.post("/admin/login", data={"password": "secret"})
        response = client.post("/admin/products/import-remote", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?import_status=remote_ok"

    with session_scope() as session:
        product = session.query(Product).filter(Product.code == "770").one()

    assert product.article == "14.023пр."
