from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import Base, Product
from database.repositories import (
    get_product_by_article,
    get_similar_products,
    lookup_products,
    search_products_structured,
)
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


def test_lookup_products_returns_multiple_exact_by_article_and_code() -> None:
    with build_session() as session:
        session.add_all(
            [
                Product(
                    code="A-1",
                    article="ART-55",
                    normalized_article="ART55",
                    retail_price=Decimal("100"),
                    raw_payload={},
                ),
                Product(
                    code="A-2",
                    article="ART-55",
                    normalized_article="ART55",
                    retail_price=Decimal("120"),
                    raw_payload={},
                ),
                Product(
                    code="B-9",
                    article="ART-559",
                    normalized_article="ART559",
                    raw_payload={},
                ),
            ]
        )
        session.commit()

        exact_by_article, similar_by_article = lookup_products(session, "ART-55")
        exact_by_code, _ = lookup_products(session, "A-2")

        assert [product.code for product in exact_by_article] == ["A-1", "A-2"]
        assert any(product.code == "B-9" for product in similar_by_article)
        assert len(exact_by_code) == 1
        assert exact_by_code[0].article == "ART-55"


def test_search_products_structured_prioritizes_exact_and_excludes_duplicates() -> None:
    with build_session() as session:
        session.add_all(
            [
                Product(
                    code="X-1",
                    article="ABC-100",
                    normalized_article="ABC100",
                    raw_payload={},
                ),
                Product(
                    code="X-2",
                    article="ABC-100",
                    normalized_article="ABC100",
                    raw_payload={},
                ),
                Product(
                    code="X-3",
                    article="ABC-100-ALT",
                    normalized_article="ABC100ALT",
                    raw_payload={},
                ),
            ]
        )
        session.commit()

        result = search_products_structured(session, query="ABC-100")

    assert result["status"] == "multiple_exact"
    assert result["exact_matches_count"] == 2
    assert result["similar_matches_count"] >= 1
    exact_codes = {item["code"] for item in result["exact_matches"]}
    similar_codes = {item["code"] for item in result["similar_matches"]}
    assert exact_codes.isdisjoint(similar_codes)


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
