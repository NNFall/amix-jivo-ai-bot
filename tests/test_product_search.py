from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import Base, Product
from database.repositories import get_product_by_article, get_similar_products
from products.product_search import ProductSearchService


def build_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_get_product_by_article_finds_exact_match() -> None:
    with build_session() as session:
        session.add(
            Product(
                code="1",
                article="AB-123",
                normalized_article="AB123",
                retail_price=Decimal("10.00"),
                corporate_price=Decimal("8.00"),
                unit="шт.",
                free_stock=Decimal("5"),
                raw_payload={},
            )
        )
        session.commit()

        product = get_product_by_article(session, "ab-123")

        assert product is not None
        assert product.article == "AB-123"


def test_get_product_by_article_finds_keyboard_variant_match() -> None:
    with build_session() as session:
        session.add(
            Product(
                code="2",
                article="OZ/700",
                normalized_article="OZ700",
                raw_payload={},
            )
        )
        session.commit()

        product = get_product_by_article(session, "ОЗ/700")

        assert product is not None
        assert product.article == "OZ/700"


def test_get_similar_products_returns_candidates() -> None:
    with build_session() as session:
        session.add_all(
            [
                Product(
                    code="1",
                    article="AB-123",
                    normalized_article="AB123",
                    raw_payload={},
                ),
                Product(
                    code="2",
                    article="AB-123-XL",
                    normalized_article="AB123XL",
                    raw_payload={},
                ),
                Product(
                    code="3",
                    article="ZZ-000",
                    normalized_article="ZZ000",
                    raw_payload={},
                ),
            ]
        )
        session.commit()

        products = get_similar_products(session, "ab-123", limit=5)

        assert [product.article for product in products] == ["AB-123", "AB-123-XL"]


def test_product_search_service_builds_readable_reply() -> None:
    product = Product(
        code="1",
        article="AB-123",
        normalized_article="AB123",
        free_stock=Decimal("7"),
        unit="шт.",
        retail_price=Decimal("125.50"),
        corporate_price=Decimal("100.00"),
        raw_payload={},
    )

    reply = ProductSearchService().build_product_reply(product)

    assert "Артикул AB-123 найден." in reply
    assert "Свободный остаток: 7 шт.." in reply
    assert "Розничная цена: 125.5 руб." in reply
