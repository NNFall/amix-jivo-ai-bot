from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from products.xml_importer import ProductXmlImporter, XmlImportResult
from settings import BASE_DIR, Settings


FetchXml = Callable[[str, int], bytes]


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
        import_result = self.xml_importer.import_file(saved_path)
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


def _fetch_xml(url: str, timeout_seconds: int) -> bytes:
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": "amix-jivo-ai-bot/1.0"})
        response.raise_for_status()
        return response.content
