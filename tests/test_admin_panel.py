from datetime import UTC, datetime

from fastapi.testclient import TestClient

from database.db import session_scope
from database.models import Product, ProductImport
from main import create_application
from settings import get_settings


def build_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    get_settings.cache_clear()
    return TestClient(create_application())


def test_admin_page_requires_basic_auth(isolated_app_env, monkeypatch) -> None:
    with build_client(monkeypatch) as client:
        response = client.get("/admin")

    assert response.status_code == 401


def test_admin_page_shows_product_status_and_xml_actions(isolated_app_env, monkeypatch) -> None:
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
        response = client.get("/admin", auth=("admin", "secret"))

    assert response.status_code == 200
    assert "AMIX AI бот" in response.text
    assert "Товаров в базе" in response.text
    assert "1" in response.text
    assert "Скачать текущую базу" in response.text
    assert "Загрузить XML" in response.text


def test_admin_downloads_current_products_as_xml(isolated_app_env, monkeypatch) -> None:
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
        response = client.get("/admin/products.xml", auth=("admin", "secret"))

    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "<Код>770</Код>" in response.text
    assert "<Артикул>14.023пр.</Артикул>" in response.text
    assert "<СвободныйОстаток>220.000</СвободныйОстаток>" in response.text


def test_admin_uploads_xml_and_imports_products(isolated_app_env, monkeypatch) -> None:
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
        response = client.post(
            "/admin/products/import",
            auth=("admin", "secret"),
            files={"file": ("products.xml", xml_payload.encode("utf-8"), "application/xml")},
            follow_redirects=False,
        )

    assert response.status_code == 303
    with session_scope() as session:
        product = session.query(Product).filter(Product.code == "22608").one()

    assert product.article == "P-AM02/B-S"
    assert str(product.free_stock) == "7.000"
