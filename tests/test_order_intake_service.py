from decimal import Decimal

from core.order_intake_service import OrderIntakeService
from database.db import session_scope
from database.models import OrderDraft, Product
from database.repositories import get_or_create_chat, get_or_create_customer
from products.article_utils import normalize_article


def _create_chat(session, external_chat_id: str = "jivo:order-1") -> None:
    customer = get_or_create_customer(session, external_client_id=f"customer:{external_chat_id}")
    get_or_create_chat(session, external_chat_id, customer.id)


def test_order_draft_accepts_free_form_item_and_waits_for_confirmation(isolated_app_env) -> None:
    service = OrderIntakeService()

    with session_scope() as session:
        _create_chat(session)
        result = service.update_draft(
            session,
            external_chat_id="jivo:order-1",
            patch={
                "items": [{"description": "чёрные петли Блюм", "quantity": 10}],
                "needed_by": "в течение недели",
                "fulfillment": {"method": "delivery", "city": "Тверь"},
                "payment": {"method": "cash"},
                "contact": {"name": "Наталья", "phone": "+7 900 000-00-00"},
            },
        )

    assert result["status"] == "ready_for_confirmation"
    assert result["missing_fields"] == []
    assert "чёрные петли Блюм — 10" in result["summary"]
    assert service.is_explicit_confirmation("Да, всё верно") is True
    assert service.is_explicit_confirmation("окей") is True
    assert service.is_explicit_confirmation("вроде да, но адрес другой") is False

    with session_scope() as session:
        draft = session.query(OrderDraft).one()

    assert draft.status == "ready_for_confirmation"


def test_bank_transfer_requires_only_name_phone_and_inn(isolated_app_env) -> None:
    service = OrderIntakeService()

    with session_scope() as session:
        _create_chat(session, "jivo:order-bank")
        result = service.update_draft(
            session,
            external_chat_id="jivo:order-bank",
            patch={
                "items": [{"identifier": "770", "quantity": 2}],
                "needed_by": "до 20 июля",
                "fulfillment": {"method": "pickup"},
                "payment": {"method": "bank_transfer", "inn": "1234567890"},
                "contact": {"name": "Иван", "phone": "+7 900 111-22-33"},
            },
        )

    assert result["status"] == "ready_for_confirmation"
    assert result["missing_fields"] == []
    assert "ИНН 1234567890" in result["summary"]


def test_bank_transfer_preserves_voluntary_invoice_details(isolated_app_env) -> None:
    service = OrderIntakeService()

    with session_scope() as session:
        _create_chat(session, "jivo:order-bank-optional")
        result = service.update_draft(
            session,
            external_chat_id="jivo:order-bank-optional",
            patch={
                "items": [{"identifier": "770", "quantity": 2}],
                "needed_by": "до 20 июля",
                "fulfillment": {"method": "pickup"},
                "payment": {
                    "method": "bank_transfer",
                    "customer_type": "legal_entity",
                    "company_name": "ООО Мебель",
                    "inn": "1234567890",
                    "kpp": "123456789",
                },
                "contact": {
                    "name": "Ирина",
                    "phone": "+7 900 111-22-33",
                    "email": "info@example.ru",
                },
            },
        )

    assert result["status"] == "ready_for_confirmation"
    assert result["data"]["payment"]["company_name"] == "ООО Мебель"
    assert result["data"]["payment"]["kpp"] == "123456789"
    assert result["data"]["contact"]["email"] == "info@example.ru"
    assert "ООО Мебель" in result["summary"]
    assert "КПП 123456789" in result["summary"]
    assert "info@example.ru" in result["summary"]


def test_bank_transfer_requires_phone_even_when_invoice_email_is_present(isolated_app_env) -> None:
    service = OrderIntakeService()

    with session_scope() as session:
        _create_chat(session, "jivo:order-bank-phone")
        result = service.update_draft(
            session,
            external_chat_id="jivo:order-bank-phone",
            patch={
                "items": [{"description": "ручки", "quantity": 5}],
                "needed_by": "до конца месяца",
                "fulfillment": {"method": "pickup"},
                "payment": {
                    "method": "bank_transfer",
                    "customer_type": "legal_entity",
                    "company_name": "ООО Мебель",
                    "inn": "1234567890",
                },
                "contact": {"name": "Ирина", "email": "info@example.ru"},
            },
        )

    assert result["status"] == "collecting"
    assert "телефон" in result["missing_fields"]


def test_non_bank_transfer_requires_phone_even_when_email_is_present(isolated_app_env) -> None:
    service = OrderIntakeService()

    with session_scope() as session:
        _create_chat(session, "jivo:order-card-phone")
        result = service.update_draft(
            session,
            external_chat_id="jivo:order-card-phone",
            patch={
                "items": [{"description": "ручки", "quantity": 5}],
                "needed_by": "до конца месяца",
                "fulfillment": {"method": "pickup"},
                "payment": {"method": "card"},
                "contact": {"name": "Ирина", "email": "info@example.ru"},
            },
        )

    assert result["status"] == "collecting"
    assert "телефон" in result["missing_fields"]


def test_order_draft_requires_desired_timing_without_promising_delivery_date(isolated_app_env) -> None:
    service = OrderIntakeService()

    with session_scope() as session:
        _create_chat(session, "jivo:order-timing")
        result = service.update_draft(
            session,
            external_chat_id="jivo:order-timing",
            patch={
                "items": [{"description": "мебельные ручки", "quantity": 5}],
                "fulfillment": {"method": "pickup"},
                "payment": {"method": "card"},
                "contact": {"name": "Ирина", "phone": "+7 900 555-44-33"},
            },
        )

    assert result["status"] == "collecting"
    assert "желаемый срок" in result["missing_fields"]


def test_identified_product_check_returns_only_yes_or_no_for_requested_quantity(isolated_app_env) -> None:
    service = OrderIntakeService()

    with session_scope() as session:
        _create_chat(session, "jivo:order-stock")
        session.add(
            Product(
                code="770",
                article="14.023пр.",
                normalized_article=normalize_article("14.023пр."),
                free_stock=Decimal("220"),
                unit="шт",
                raw_payload={},
            )
        )
        result = service.update_draft(
            session,
            external_chat_id="jivo:order-stock",
            patch={"items": [{"identifier": "770", "quantity": 2}]},
        )

    assert result["product_checks"] == [
        {
            "identifier": "770",
            "code": "770",
            "article": "14.023пр.",
            "requested_quantity": 2,
            "available": True,
            "status": "exact_found",
        }
    ]
    assert "stock" not in str(result["product_checks"]).lower()
    assert "220" not in str(result)


def test_identified_product_with_unknown_stock_keeps_availability_unknown(isolated_app_env) -> None:
    service = OrderIntakeService()

    with session_scope() as session:
        _create_chat(session, "jivo:order-stock-unknown")
        session.add(
            Product(
                code="771",
                article="UNKNOWN-STOCK",
                normalized_article=normalize_article("UNKNOWN-STOCK"),
                free_stock=None,
                unit="шт",
                raw_payload={},
            )
        )
        result = service.update_draft(
            session,
            external_chat_id="jivo:order-stock-unknown",
            patch={"items": [{"identifier": "771", "quantity": 2}]},
        )

    assert result["product_checks"][0]["status"] == "exact_found"
    assert result["product_checks"][0]["available"] is None
