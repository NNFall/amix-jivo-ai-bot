from pathlib import Path

from database.db import session_scope
from database.models import Product, ProductImport
from products.xml_importer import ProductXmlImporter


def test_xml_importer_success_and_update(isolated_app_env, tmp_path: Path) -> None:
    xml_path = tmp_path / "products.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<root>
  <product>
    <code>001</code>
    <article>AB-123</article>
    <retailprice>100.50</retailprice>
    <corporateprice>90</corporateprice>
    <unit>шт.</unit>
    <freestock>5</freestock>
  </product>
  <product>
    <code>002</code>
    <article>CD-777</article>
    <retailprice>210</retailprice>
    <freestock>0</freestock>
  </product>
</root>
""",
        encoding="utf-8",
    )

    importer = ProductXmlImporter()
    first_result = importer.import_file(xml_path)

    assert first_result.status == "completed"
    assert first_result.processed == 2
    assert first_result.created == 2
    assert first_result.updated == 0
    assert first_result.errors == 0

    xml_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<root>
  <product>
    <code>001</code>
    <article>AB-123</article>
    <retailprice>110</retailprice>
    <freestock>7</freestock>
  </product>
</root>
""",
        encoding="utf-8",
    )
    second_result = importer.import_file(xml_path)

    assert second_result.status == "completed"
    assert second_result.processed == 1
    assert second_result.created == 0
    assert second_result.updated == 1

    with session_scope() as session:
        products = session.query(Product).order_by(Product.code.asc()).all()
        imports = session.query(ProductImport).order_by(ProductImport.id.asc()).all()

    assert len(products) == 2
    assert len(imports) == 2
    assert imports[0].status == "completed"
    assert imports[1].status == "completed"
    assert imports[1].updated_count == 1


def test_xml_importer_parse_error_marks_import_failed(isolated_app_env, tmp_path: Path) -> None:
    xml_path = tmp_path / "broken.xml"
    xml_path.write_text("<root><product><code>001</code></product>", encoding="utf-8")

    result = ProductXmlImporter().import_file(xml_path)

    assert result.status == "failed"
    assert result.errors == 1
    assert result.error_text is not None
    assert "parse error" in result.error_text.lower()

    with session_scope() as session:
        imports = session.query(ProductImport).all()
        products = session.query(Product).all()

    assert len(imports) == 1
    assert imports[0].status == "failed"
    assert imports[0].error_count == 1
    assert len(products) == 0


def test_xml_importer_skips_non_normalizable_article(isolated_app_env, tmp_path: Path) -> None:
    xml_path = tmp_path / "skipped.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<root>
  <product>
    <article>---</article>
    <retailprice>11</retailprice>
  </product>
  <product>
    <article>EF-100</article>
    <retailprice>11</retailprice>
  </product>
</root>
""",
        encoding="utf-8",
    )

    result = ProductXmlImporter().import_file(xml_path)

    assert result.status == "completed"
    assert result.processed == 1
    assert result.created == 1
    assert result.skipped == 1
    assert result.errors == 0
