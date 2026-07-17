from decimal import Decimal

from database.db import session_scope
from database.models import Product
from database.repositories import search_products_structured


def seed_eval_products() -> None:
    products = [
        Product(
            code="22608",
            article="P-AM02/B-S",
            normalized_article="PAM02BS",
            free_stock=Decimal("1"),
            unit="шт",
            weight=Decimal("0.638"),
            raw_payload={},
        ),
        Product(
            code="1364",
            article="14.025пр.",
            normalized_article="14025ПР",
            retail_price=Decimal("238"),
            corporate_price=Decimal("165.98"),
            free_stock=Decimal("7"),
            unit="шт",
            weight=Decimal("0.07"),
            raw_payload={},
        ),
        Product(
            code="769",
            article="14.023л.",
            normalized_article="14023Л",
            retail_price=Decimal("473"),
            corporate_price=Decimal("335.24"),
            free_stock=Decimal("253"),
            unit="шт",
            weight=Decimal("0.07"),
            raw_payload={},
        ),
        Product(
            code="770",
            article="14.023пр.",
            normalized_article="14023ПР",
            retail_price=Decimal("473"),
            corporate_price=Decimal("335.24"),
            free_stock=Decimal("220"),
            unit="шт",
            weight=Decimal("0.07"),
            raw_payload={},
        ),
        Product(
            code="10001",
            article="ABC-100",
            normalized_article="ABC100",
            retail_price=Decimal("120"),
            free_stock=Decimal("5"),
            unit="шт",
            raw_payload={},
        ),
        Product(
            code="10002",
            article="ABC-100",
            normalized_article="ABC100",
            retail_price=Decimal("140"),
            free_stock=Decimal("8"),
            unit="шт",
            raw_payload={},
        ),
    ]
    with session_scope() as session:
        session.add_all(products)


def test_product_lookup_regression_set(isolated_app_env) -> None:
    seed_eval_products()

    with session_scope() as session:
        exact_article = search_products_structured(session, query="14.025пр.")
        exact_code = search_products_structured(session, query="1364")
        slash_article = search_products_structured(session, query="P-AM02/B-S")
        duplicate_article = search_products_structured(session, query="ABC-100")
        similar_article = search_products_structured(session, query="14.023")
        exact_not_similar = search_products_structured(session, query="14.023пр.")
        dirty_article = search_products_structured(session, query="p am02 b s")
        missing = search_products_structured(session, query="XYZ-999")

    assert exact_article["status"] == "exact_found"
    assert exact_article["exact_matches"][0]["code"] == "1364"
    assert exact_code["status"] == "exact_found"
    assert exact_code["exact_matches"][0]["article"] == "14.025пр."
    assert slash_article["status"] == "exact_found"
    assert slash_article["exact_matches"][0]["code"] == "22608"
    assert duplicate_article["status"] == "multiple_exact"
    assert {item["code"] for item in duplicate_article["exact_matches"]} == {"10001", "10002"}
    assert similar_article["status"] == "similar_found"
    assert {item["code"] for item in similar_article["similar_matches"]} >= {"769", "770"}
    assert exact_not_similar["status"] == "exact_found"
    assert all(item["code"] != "770" for item in exact_not_similar["similar_matches"])
    assert dirty_article["status"] == "exact_found"
    assert missing["status"] == "not_found"
