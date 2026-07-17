from products.article_utils import build_normalized_article_variants, normalize_article


def test_normalize_article_removes_separators() -> None:
    assert normalize_article(" ab-12 / 34 ") == "AB1234"


def test_normalize_article_normalizes_cyrillic_yo() -> None:
    assert normalize_article("ёж-01") == "ЕЖ01"


def test_build_normalized_article_variants_handles_mixed_alphabets() -> None:
    assert build_normalized_article_variants("ОЗ/700") == ["ОЗ700", "OZ700"]


def test_build_normalized_article_variants_maps_identifier_characters() -> None:
    assert "MP28CK" in build_normalized_article_variants("МП 28ск")
