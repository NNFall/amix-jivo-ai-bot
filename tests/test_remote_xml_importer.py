import asyncio
import os
import time
from pathlib import Path

from database.db import session_scope
from database.models import Product, ProductImport
from products.remote_xml_importer import ProductRemoteXmlImporter
from products.remote_xml_scheduler import ProductsXmlAutoImportRunner


def test_remote_xml_importer_prunes_only_old_automatic_snapshots(isolated_app_env, tmp_path: Path) -> None:
    old_files = []
    for day in range(5):
        path = tmp_path / f"2026010{day + 1}-120000-remote-prices.xml"
        path.write_bytes(b"old")
        os.utime(path, (time.time() - 72 * 3600 - day, time.time() - 72 * 3600 - day))
        old_files.append(path)
    fresh = tmp_path / "20260106-120000-remote-prices.xml"
    fresh.write_bytes(b"fresh")
    manual = tmp_path / "20260101-120000-products.xml"
    manual.write_bytes(b"manual")

    importer = ProductRemoteXmlImporter(
        url="https://example.test/prices.xml",
        timeout_seconds=12,
        incoming_dir=tmp_path,
        fetcher=lambda url, timeout_seconds: b"<root></root>",
    )
    result = importer.download_and_import()

    assert result.status == "completed"
    assert result.saved_path is not None and result.saved_path.exists()
    assert old_files[0].exists()  # Keep a third recent snapshot even if it is older than the cutoff.
    assert all(not path.exists() for path in old_files[1:])
    assert fresh.exists()
    assert manual.exists()


def test_remote_xml_importer_prunes_after_invalid_xml(isolated_app_env, tmp_path: Path) -> None:
    stale = tmp_path / "20260101-120000-remote-prices.xml"
    stale.write_bytes(b"old")
    os.utime(stale, (time.time() - 72 * 3600, time.time() - 72 * 3600))
    for day in range(3):
        (tmp_path / f"2026010{day + 2}-120000-remote-prices.xml").write_bytes(b"recent")

    importer = ProductRemoteXmlImporter(
        url="https://example.test/prices.xml",
        timeout_seconds=12,
        incoming_dir=tmp_path,
        fetcher=lambda url, timeout_seconds: b"<root>",
    )
    result = importer.download_and_import()

    assert result.status == "failed"
    assert result.saved_path is not None and result.saved_path.exists()
    assert not stale.exists()


def test_remote_xml_importer_preserves_last_successful_snapshot(isolated_app_env, tmp_path: Path) -> None:
    successful = tmp_path / "20260101-120000-remote-prices.xml"
    successful.write_bytes(b"last good payload")
    stale = tmp_path / "20260102-120000-remote-prices.xml"
    stale.write_bytes(b"old failed payload")
    for path in (successful, stale):
        os.utime(path, (time.time() - 72 * 3600, time.time() - 72 * 3600))
    for day in range(3):
        (tmp_path / f"2026010{day + 3}-120000-remote-prices.xml").write_bytes(b"new failed payload")
    with session_scope() as session:
        session.add(
            ProductImport(
                filename=successful.name,
                source_path=str(successful),
                status="completed",
                imported_count=1,
                error_count=0,
            )
        )

    importer = ProductRemoteXmlImporter(
        url="https://example.test/prices.xml",
        timeout_seconds=12,
        incoming_dir=tmp_path,
        fetcher=lambda url, timeout_seconds: b"<root>",
    )
    result = importer.download_and_import()

    assert result.status == "failed"
    assert successful.exists()
    assert not stale.exists()


def test_remote_xml_importer_preserves_largest_successful_snapshot(isolated_app_env, tmp_path: Path) -> None:
    full = tmp_path / "20260101-120000-remote-prices.xml"
    full.write_bytes(b"full payload" * 100)
    partial = tmp_path / "20260102-120000-remote-prices.xml"
    partial.write_bytes(b"partial")
    stale = tmp_path / "20260103-120000-remote-prices.xml"
    stale.write_bytes(b"old failure")
    for path in (full, partial, stale):
        os.utime(path, (time.time() - 72 * 3600, time.time() - 72 * 3600))
    for day in range(3):
        (tmp_path / f"2026010{day + 4}-120000-remote-prices.xml").write_bytes(b"new failure")
    with session_scope() as session:
        for path in (full, partial):
            session.add(
                ProductImport(
                    filename=path.name,
                    source_path=str(path),
                    status="completed",
                    imported_count=1,
                    error_count=0,
                )
            )

    importer = ProductRemoteXmlImporter(
        url="https://example.test/prices.xml",
        timeout_seconds=12,
        incoming_dir=tmp_path,
        fetcher=lambda url, timeout_seconds: b"<root>",
    )
    result = importer.download_and_import()

    assert result.status == "failed"
    assert full.exists()
    assert partial.exists()
    assert not stale.exists()


def test_remote_xml_importer_downloads_and_imports_products(
    isolated_app_env,
    tmp_path: Path,
) -> None:
    xml_payload = """<?xml version="1.0" encoding="utf-8"?>
<root>
  <record>
    <Код>770</Код>
    <Артикул>14.023пр.</Артикул>
    <ЦенаРозничная>473.00</ЦенаРозничная>
    <ЕдиницаИзмерения>шт</ЕдиницаИзмерения>
    <СвободныйОстаток>220.00</СвободныйОстаток>
  </record>
</root>
"""

    def fake_fetcher(url: str, timeout_seconds: int) -> bytes:
        assert url == "https://example.test/prices.xml"
        assert timeout_seconds == 12
        return xml_payload.encode("utf-8")

    importer = ProductRemoteXmlImporter(
        url="https://example.test/prices.xml",
        timeout_seconds=12,
        incoming_dir=tmp_path,
        fetcher=fake_fetcher,
    )

    result = importer.download_and_import()

    assert result.status == "completed"
    assert result.downloaded_bytes == len(xml_payload.encode("utf-8"))
    assert result.saved_path is not None
    assert result.saved_path.exists()
    assert result.import_result is not None
    assert result.import_result.processed == 1

    with session_scope() as session:
        product = session.query(Product).filter(Product.code == "770").one()
        imports = session.query(ProductImport).all()

    assert product.article == "14.023пр."
    assert str(product.free_stock) == "220.000"
    assert len(imports) == 1
    assert imports[0].status == "completed"


def test_remote_xml_importer_reports_download_error(
    isolated_app_env,
    tmp_path: Path,
) -> None:
    def failing_fetcher(url: str, timeout_seconds: int) -> bytes:
        raise TimeoutError("download timed out")

    importer = ProductRemoteXmlImporter(
        url="https://example.test/prices.xml",
        timeout_seconds=12,
        incoming_dir=tmp_path,
        fetcher=failing_fetcher,
    )

    result = importer.download_and_import()

    assert result.status == "failed"
    assert "download timed out" in (result.error_text or "")
    assert result.import_result is None

    with session_scope() as session:
        assert session.query(ProductImport).count() == 0


def test_remote_xml_importer_removes_products_missing_from_latest_feed(
    isolated_app_env,
    tmp_path: Path,
) -> None:
    with session_scope() as session:
        session.add(
            Product(
                code="OLD",
                article="OLD-ARTICLE",
                normalized_article="OLDARTICLE",
                free_stock=1,
                raw_payload={},
            )
        )

    xml_payload = """<?xml version="1.0" encoding="utf-8"?>
<root>
  <record>
    <Код>770</Код>
    <Артикул>14.023пр.</Артикул>
    <СвободныйОстаток>220.00</СвободныйОстаток>
  </record>
</root>
"""

    importer = ProductRemoteXmlImporter(
        url="https://example.test/prices.xml",
        timeout_seconds=12,
        incoming_dir=tmp_path,
        fetcher=lambda url, timeout_seconds: xml_payload.encode("utf-8"),
    )

    result = importer.download_and_import()

    assert result.status == "completed"
    assert result.import_result is not None
    assert result.import_result.deleted == 1

    with session_scope() as session:
        products = session.query(Product).order_by(Product.code.asc()).all()

    assert [product.code for product in products] == ["770"]


def test_auto_import_runner_runs_once_on_startup_and_stops() -> None:
    asyncio.run(_run_auto_import_runner_once())


async def _run_auto_import_runner_once() -> None:
    calls = 0
    first_call = asyncio.Event()

    def import_once() -> None:
        nonlocal calls
        calls += 1
        first_call.set()

    runner = ProductsXmlAutoImportRunner(
        import_once=import_once,
        interval_seconds=3600,
        run_on_startup=True,
    )

    await runner.start()
    await asyncio.wait_for(first_call.wait(), timeout=1)
    await runner.stop()

    assert calls == 1
