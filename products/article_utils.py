import re


CYR_TO_LAT = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "Е": "E",
        "З": "Z",
        "К": "K",
        "М": "M",
        "Н": "H",
        "О": "O",
        "П": "P",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "У": "Y",
        "Х": "X",
    }
)

LAT_TO_CYR = str.maketrans(
    {
        "A": "А",
        "B": "В",
        "C": "С",
        "E": "Е",
        "H": "Н",
        "K": "К",
        "M": "М",
        "O": "О",
        "P": "П",
        "T": "Т",
        "X": "Х",
        "Y": "У",
        "Z": "З",
    }
)


def normalize_article(article: str) -> str:
    """Normalize one query already selected by the model for catalog matching."""
    prepared = article.strip().upper().replace("Ё", "Е")
    return re.sub(r"[^0-9A-ZА-Я]+", "", prepared)


def build_normalized_article_variants(article: str) -> list[str]:
    """Handle visually identical Cyrillic and Latin characters inside a product identifier."""
    normalized = normalize_article(article)
    if not normalized:
        return []

    variants = [normalized]
    for variant in (normalized.translate(CYR_TO_LAT), normalized.translate(LAT_TO_CYR)):
        if variant and variant not in variants:
            variants.append(variant)
    return variants
