from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import Base, Product
from database.repositories import (
    lookup_products,
    search_products_structured,
)


def build_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


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


def test_search_products_structured_treats_compact_split_article_as_exact() -> None:
    with build_session() as session:
        session.add(
            Product(
                code="22608",
                article="P-AM02/B-S",
                normalized_article="PAM02BS",
                raw_payload={},
            )
        )
        session.commit()

        result = search_products_structured(session, query="p am02 b s")

    assert result["status"] == "exact_found"
    assert result["exact_matches"][0]["code"] == "22608"


def test_search_products_structured_matches_description_words_in_any_order() -> None:
    with build_session() as session:
        session.add(
            Product(
                code="5001",
                article="Белая мебельная ручка 128 мм",
                normalized_article="БЕЛАЯМЕБЕЛЬНАЯРУЧКА128ММ",
                raw_payload={},
            )
        )
        session.commit()

        result = search_products_structured(
            session,
            query="ручка мебельная 128 мм белая",
        )

    assert result["status"] == "exact_found"
    assert result["exact_matches"][0]["code"] == "5001"


def test_search_products_structured_ignores_sentence_punctuation_around_code() -> None:
    with build_session() as session:
        session.add(
            Product(
                code="10002",
                article="ABC-100",
                normalized_article="ABC100",
                raw_payload={},
            )
        )
        session.commit()

        result = search_products_structured(session, query="10002.")

    assert result["status"] == "exact_found"
    assert result["exact_matches"][0]["code"] == "10002"


def test_search_products_structured_includes_price_display_fields() -> None:
    with build_session() as session:
        session.add(
            Product(
                code="770",
                article="14.023пр.",
                normalized_article="14023ПР",
                retail_price=Decimal("473.00"),
                corporate_price=Decimal("335.24"),
                raw_payload={},
            )
        )
        session.commit()

        result = search_products_structured(session, query="14.023пр.")

    match = result["exact_matches"][0]
    assert match["retail_price_display"] == "473 руб."
    assert match["corporate_price_display"] == "335,24 руб."
