from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from database.repositories import get_order_draft, search_products_structured, upsert_order_draft


class OrderIntakeService:
    def update_draft(self, session, *, external_chat_id: str, patch: dict[str, Any] | None) -> dict[str, Any]:
        session.flush()
        existing = get_order_draft(session, external_chat_id)
        data = deepcopy(existing.data) if existing else {}
        data = self._merge_patch(data, patch or {})
        missing_fields = self._missing_fields(data)
        if missing_fields:
            status = "collecting"
        elif existing and existing.status == "awaiting_confirmation" and data == existing.data:
            status = "awaiting_confirmation"
        else:
            status = "ready_for_confirmation"
        summary = self._build_summary(data) if not missing_fields else None
        product_checks = self._check_products(session, data.get("items", []))

        upsert_order_draft(
            session,
            external_chat_id=external_chat_id,
            status=status,
            data=data,
            summary=summary,
        )
        return {
            "status": status,
            "data": data,
            "missing_fields": missing_fields,
            "summary": summary,
            "product_checks": product_checks,
        }

    def get_context(self, session, external_chat_id: str) -> dict[str, Any] | None:
        draft = get_order_draft(session, external_chat_id)
        if draft is None:
            return None
        return {
            "status": draft.status,
            "data": deepcopy(draft.data),
            "missing_fields": self._missing_fields(draft.data),
            "summary": draft.summary,
        }

    def mark_handed_off(self, session, external_chat_id: str) -> None:
        draft = get_order_draft(session, external_chat_id)
        if draft is None:
            return
        draft.status = "handed_off"
        session.add(draft)

    def mark_summary_shown(self, session, external_chat_id: str) -> None:
        draft = get_order_draft(session, external_chat_id)
        if draft is None or not draft.summary or self._missing_fields(draft.data):
            return
        draft.status = "awaiting_confirmation"
        session.add(draft)

    @staticmethod
    def is_explicit_confirmation(text: str) -> bool:
        normalized = re.sub(r"[^a-zа-яё0-9]+", " ", (text or "").lower()).strip()
        return normalized in {
            "да",
            "да верно",
            "да все верно",
            "да всё верно",
            "все верно",
            "всё верно",
            "верно",
            "подтверждаю",
            "да подтверждаю",
            "ок",
            "окей",
            "все правильно",
            "всё правильно",
        }

    def _merge_patch(self, current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(current)
        if "items" in patch and isinstance(patch["items"], list):
            result["items"] = [self._normalize_item(item) for item in patch["items"] if isinstance(item, dict)]

        for section in ("fulfillment", "payment", "contact"):
            incoming = patch.get(section)
            if not isinstance(incoming, dict):
                continue
            merged = dict(result.get(section) or {})
            for key, value in incoming.items():
                if value is not None and str(value).strip():
                    merged[key] = value
            result[section] = merged

        for field in ("needed_by", "notes"):
            if field in patch and patch[field] is not None:
                result[field] = str(patch[field]).strip()
        return result

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for field in ("identifier", "description"):
            value = item.get(field)
            if value is not None and str(value).strip():
                normalized[field] = str(value).strip()
        quantity = self._to_number(item.get("quantity"))
        if quantity is not None:
            normalized["quantity"] = quantity
        return normalized

    def _missing_fields(self, data: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        items = data.get("items") or []
        if not items or any(
            not (item.get("identifier") or item.get("description")) or not self._positive_number(item.get("quantity"))
            for item in items
        ):
            missing.append("товары и количество")
        if not data.get("needed_by"):
            missing.append("желаемый срок")

        fulfillment = data.get("fulfillment") or {}
        method = fulfillment.get("method")
        if method not in {"pickup", "delivery"}:
            missing.append("способ получения")
        elif method == "delivery" and not fulfillment.get("city"):
            missing.append("город доставки")

        payment = data.get("payment") or {}
        payment_method = payment.get("method")
        if payment_method not in {"cash", "card", "online", "bank_transfer"}:
            missing.append("способ оплаты")

        contact = data.get("contact") or {}
        if not contact.get("name"):
            missing.append("имя контактного лица")

        if payment_method == "bank_transfer":
            if not contact.get("phone"):
                missing.append("телефон")
            if payment.get("customer_type") not in {"legal_entity", "individual_entrepreneur"}:
                missing.append("тип плательщика")
            if not payment.get("company_name"):
                missing.append("название организации или ИП")
            if not payment.get("inn"):
                missing.append("ИНН")
            if not contact.get("email"):
                missing.append("email для счёта")
        elif not (contact.get("phone") or contact.get("email")):
            missing.append("телефон или email")
        return missing

    def _check_products(self, session, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        for item in items:
            identifier = str(item.get("identifier") or "").strip()
            if not identifier:
                continue
            lookup = search_products_structured(session, query=identifier)
            exact_matches = lookup.get("exact_matches", [])
            check: dict[str, Any] = {
                "identifier": identifier,
                "requested_quantity": item.get("quantity"),
                "available": None,
                "status": lookup.get("status"),
            }
            if len(exact_matches) == 1:
                product = exact_matches[0]
                check["code"] = product.get("code")
                check["article"] = product.get("article")
                requested = self._to_decimal(item.get("quantity"))
                available = self._to_decimal(product.get("stock"))
                if requested is not None and available is not None:
                    check["available"] = available >= requested
            checks.append(check)
        return checks

    def _build_summary(self, data: dict[str, Any]) -> str:
        item_lines = []
        for item in data.get("items", []):
            label = item.get("identifier") or item.get("description")
            item_lines.append(f"{label} — {self._format_number(item.get('quantity'))}")

        fulfillment = data.get("fulfillment") or {}
        fulfillment_text = "самовывоз"
        if fulfillment.get("method") == "delivery":
            fulfillment_text = f"доставка в {fulfillment.get('city')}"

        payment = data.get("payment") or {}
        payment_names = {
            "cash": "наличными",
            "card": "картой",
            "online": "онлайн",
            "bank_transfer": "по безналичному расчёту",
        }
        contact = data.get("contact") or {}
        contact_parts = [contact.get("name"), contact.get("phone"), contact.get("email")]
        lines = [
            "Товары: " + "; ".join(item_lines),
            "Желаемый срок: " + str(data.get("needed_by")),
            "Получение: " + fulfillment_text,
            "Оплата: " + payment_names.get(payment.get("method"), str(payment.get("method") or "")),
            "Контакт: " + ", ".join(str(value) for value in contact_parts if value),
        ]
        if payment.get("method") == "bank_transfer":
            customer_types = {
                "legal_entity": "организация",
                "individual_entrepreneur": "ИП",
            }
            payer = [
                customer_types.get(payment.get("customer_type")),
                payment.get("company_name"),
                f"ИНН {payment.get('inn')}",
            ]
            if payment.get("kpp"):
                payer.append(f"КПП {payment.get('kpp')}")
            lines.append("Плательщик: " + ", ".join(str(value) for value in payer if value))
        if data.get("notes"):
            lines.append("Комментарий: " + str(data["notes"]))
        return "\n".join(lines)

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        try:
            if value is None or isinstance(value, bool):
                return None
            return Decimal(str(value).replace(",", "."))
        except (InvalidOperation, ValueError):
            return None

    def _to_number(self, value: Any) -> int | float | None:
        decimal_value = self._to_decimal(value)
        if decimal_value is None or decimal_value <= 0:
            return None
        if decimal_value == decimal_value.to_integral_value():
            return int(decimal_value)
        return float(decimal_value)

    def _positive_number(self, value: Any) -> bool:
        decimal_value = self._to_decimal(value)
        return decimal_value is not None and decimal_value > 0

    @staticmethod
    def _format_number(value: Any) -> str:
        if isinstance(value, float):
            return str(value).replace(".", ",")
        return str(value)
