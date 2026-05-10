from argparse import ArgumentParser

from products.xml_importer import ProductXmlImporter


def main() -> None:
    parser = ArgumentParser(description="Import product XML into the local database.")
    parser.add_argument("--path", required=True, help="Path to the XML file")
    args = parser.parse_args()

    result = ProductXmlImporter().import_file(args.path)
    print(
        "Import finished:",
        f"processed={result.processed}",
        f"created={result.created}",
        f"updated={result.updated}",
    )


if __name__ == "__main__":
    main()
