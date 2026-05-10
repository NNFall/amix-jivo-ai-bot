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
    "corporate_price": {"corporateprice", "корпоративнаяцена", "pricecorp", "priceopt"},
    "retail_price": {"retailprice", "розничнаяцена", "priceretail", "price"},
    "unit": {"unit", "единицаизмерения", "uom"},
    "weight": {"weight", "вес"},
    "volume": {"volume", "объем", "объём"},
    "free_stock": {"freestock", "свободныйостаток", "stock", "quantity"},
}


@dataclass(slots=True)
class XmlImportResult:
    processed: int = 0
    created: int = 0
    updated: int = 0


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
        result = XmlImportResult()

        with session_scope() as session:
            import_row = create_product_import(session, source_path.name, str(source_path))

            tree = ElementTree.parse(source_path)
            root = tree.getroot()

            for record in self._iter_candidate_records(root):
                article = self._pick(record, "article")
                code = self._pick(record, "code")
                normalized_article = normalize_article(article) if article else ""
                if not code and not normalized_article:
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
                result.processed += 1
                if created:
                    result.created += 1
                else:
                    result.updated += 1

            finish_product_import(
                session,
                import_row,
                status="completed",
                imported_count=result.created,
                updated_count=result.updated,
                error_count=0,
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
