from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from pathlib import Path
import re

import httpx

from database.db import session_scope
from database.models import ProductImport
from products.xml_importer import ProductXmlImporter, XmlImportResult
from settings import BASE_DIR, Settings


FetchXml = Callable[[str, int], bytes]
logger = logging.getLogger(__name__)
REMOTE_XML_NAME = re.compile(r"[0-9]{8}-[0-9]{6}-remote-prices\.xml\Z")
REMOTE_XML_RETENTION_SECONDS = 48 * 60 * 60
REMOTE_XML_MIN_SNAPSHOTS = 3


@dataclass(slots=True)
class RemoteXmlImportResult:
    status: str
    source_url: str
    saved_path: Path | None = None
    downloaded_bytes: int = 0
    import_result: XmlImportResult | None = None
    error_text: str | None = None


class ProductRemoteXmlImporter:
    def __init__(
        self,
        *,
        url: str,
        timeout_seconds: int,
        incoming_dir: Path | None = None,
        fetcher: FetchXml | None = None,
        xml_importer: ProductXmlImporter | None = None,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.incoming_dir = incoming_dir or BASE_DIR / "data" / "incoming_xml"
        self.fetcher = fetcher or _fetch_xml
        self.xml_importer = xml_importer or ProductXmlImporter(delete_missing=True)

    @classmethod
    def from_settings(cls, settings: Settings) -> "ProductRemoteXmlImporter":
        return cls(
            url=settings.products_xml_remote_url,
            timeout_seconds=settings.products_xml_download_timeout_seconds,
        )

    def download_and_import(self) -> RemoteXmlImportResult:
        try:
            payload = self.fetcher(self.url, self.timeout_seconds)
        except Exception as exc:
            return RemoteXmlImportResult(
                status="failed",
                source_url=self.url,
                error_text=f"Download failed: {exc}",
            )

        saved_path = self._save_payload(payload)
        try:
            import_result = self.xml_importer.import_file(saved_path)
        finally:
            try:
                self._prune_old_downloads(saved_path)
            except OSError:
                logger.exception("Could not prune old remote product XML snapshots")
        status = "completed" if import_result.status == "completed" else "failed"
        return RemoteXmlImportResult(
            status=status,
            source_url=self.url,
            saved_path=saved_path,
            downloaded_bytes=len(payload),
            import_result=import_result,
            error_text=import_result.error_text,
        )

    def _save_payload(self, payload: bytes) -> Path:
        self.incoming_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        path = self.incoming_dir / f"{timestamp}-remote-prices.xml"
        path.write_bytes(payload)
        return path

    def _prune_old_downloads(self, current_path: Path) -> None:
        root = self.incoming_dir.resolve(strict=True)
        with session_scope() as session:
            successful_files = (
                session.query(ProductImport.filename)
                .filter(ProductImport.status == "completed")
                .filter(ProductImport.error_count == 0)
                .filter(ProductImport.imported_count + ProductImport.updated_count > 0)
                .order_by(ProductImport.id.desc())
                .all()
            )
        completed_paths = [
            root / filename
            for (filename,) in successful_files
            if REMOTE_XML_NAME.fullmatch(filename)
            and (root / filename).is_file()
            and not (root / filename).is_symlink()
        ]
        last_successful = completed_paths[0] if completed_paths else None
        largest_successful = max(completed_paths, key=lambda path: path.stat().st_size, default=None)
        candidates = []
        for path in root.iterdir():
            if not REMOTE_XML_NAME.fullmatch(path.name) or path.is_symlink() or not path.is_file():
                continue
            candidates.append((path.stat().st_mtime, path))

        candidates.sort(reverse=True)
        cutoff = datetime.now(UTC).timestamp() - REMOTE_XML_RETENTION_SECONDS
        for _, path in candidates[REMOTE_XML_MIN_SNAPSHOTS:]:
            if path in {current_path, last_successful, largest_successful} or path.resolve(strict=True).parent != root:
                continue
            if path.stat().st_mtime < cutoff:
                path.unlink()


def _fetch_xml(url: str, timeout_seconds: int) -> bytes:
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": "amix-jivo-ai-bot/1.0"})
        response.raise_for_status()
        return response.content
