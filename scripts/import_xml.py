from argparse import ArgumentParser
from pathlib import Path
import sys

# Allow running the script directly from repository root on Windows/Linux.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from products.xml_importer import ProductXmlImporter


def main() -> None:
    parser = ArgumentParser(description="Import product XML into the local database.")
    parser.add_argument("--path", required=True, help="Path to the XML file")
    args = parser.parse_args()

    try:
        result = ProductXmlImporter().import_file(args.path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Import failed: {exc}")
        raise SystemExit(1)
    print(
        "Import finished:",
        f"status={result.status}",
        f"processed={result.processed}",
        f"created={result.created}",
        f"updated={result.updated}",
        f"skipped={result.skipped}",
        f"errors={result.errors}",
    )
    if result.error_text:
        print(f"error_text={result.error_text}")

    if result.status != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
