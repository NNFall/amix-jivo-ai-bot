from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

from database.db import session_scope
from database.repositories import create_product_import, finish_product_import, upsert_product
from products.article_utils import normalize_article


FIELD_ALIASES = {
    "code": {"code", "код", "guid", "id"},
    "article": {"article", "артикул", "vendorcode", "sku"},
    "corporate_price": {
        "corporateprice",
        "корпоративнаяцена",
        "ценакорпоративная",
        "pricecorp",
        "priceopt",
    },
    "retail_price": {
        "retailprice",
        "розничнаяцена",
        "ценарозничная",
        "priceretail",
        "price",
    },
    "unit": {"unit", "единицаизмерения", "uom"},
    "weight": {"weight", "вес"},
    "volume": {"volume", "объем", "объём"},
    "free_stock": {"freestock", "свободныйостаток", "stock", "quantity"},
}


@dataclass(slots=True)
class XmlImportResult:
    status: str = "completed"
    processed: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    error_text: str | None = None


def _normalize_tag(tag: str) -> str:
    return "".join(character for character in tag.lower() if character.isalnum())


def _to_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None

    cleaned = value.strip().replace(",", ".")
    if not cleaned:
        return None

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


class ProductXmlImporter:
    def import_file(self, xml_path: str | Path) -> XmlImportResult:
        source_path = Path(xml_path)
        result = XmlImportResult(status="completed")

        if not source_path.exists():
            raise FileNotFoundError(f"XML file was not found: {source_path}")
        if not source_path.is_file():
            raise ValueError(f"XML path is not a file: {source_path}")

        with session_scope() as session:
            import_row = create_product_import(session, source_path.name, str(source_path))
            try:
                tree = ElementTree.parse(source_path)
                root = tree.getroot()
            except ElementTree.ParseError as exc:
                result.status = "failed"
                result.errors += 1
                result.error_text = f"XML parse error: {exc}"
                finish_product_import(
                    session,
                    import_row,
                    status=result.status,
                    imported_count=result.created,
                    updated_count=result.updated,
                    error_count=result.errors,
                    error_text=result.error_text,
                )
                return result

            try:
                for record in self._iter_candidate_records(root):
                    try:
                        article = self._pick(record, "article")
                        code = self._pick(record, "code")
                        normalized_article = normalize_article(article) if article else ""

                        if not code and not normalized_article:
                            result.skipped += 1
                            continue

                        _, created = upsert_product(
                            session,
                            code=code,
                            article=article or normalized_article,
                            normalized_article=normalized_article,
                            corporate_price=_to_decimal(self._pick(record, "corporate_price")),
                            retail_price=_to_decimal(self._pick(record, "retail_price")),
                            unit=self._pick(record, "unit"),
                            weight=_to_decimal(self._pick(record, "weight")),
                            volume=_to_decimal(self._pick(record, "volume")),
                            free_stock=_to_decimal(self._pick(record, "free_stock")),
                            raw_payload=record,
                        )
                    except Exception:
                        result.errors += 1
                        continue

                    result.processed += 1
                    if created:
                        result.created += 1
                    else:
                        result.updated += 1
            except Exception as exc:
                result.status = "failed"
                result.errors += 1
                result.error_text = f"Import loop failed: {exc}"

            finish_product_import(
                session,
                import_row,
                status=result.status,
                imported_count=result.created,
                updated_count=result.updated,
                error_count=result.errors,
                error_text=result.error_text,
            )

        return result

    def _iter_candidate_records(self, root):
        for element in root.iter():
            children = list(element)
            if not children:
                continue

            record = {
                _normalize_tag(child.tag): (child.text or "").strip()
                for child in children
                if not list(child)
            }

            if len(record) < 2:
                continue

            if self._pick(record, "article") or self._pick(record, "code"):
                yield record

    @staticmethod
    def _pick(record: dict[str, str], field: str) -> str | None:
        aliases = FIELD_ALIASES[field]
        for key, value in record.items():
            if key in aliases and value:
                return value
        return None
