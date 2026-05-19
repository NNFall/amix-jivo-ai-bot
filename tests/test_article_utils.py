from products.article_utils import (
    build_normalized_article_variants,
    extract_article_candidates,
    normalize_article,
)


def test_normalize_article_removes_separators() -> None:
    assert normalize_article(" ab-12 / 34 ") == "AB1234"


def test_normalize_article_normalizes_cyrillic_yo() -> None:
    assert normalize_article("ёж-01") == "ЕЖ01"


def test_extract_article_candidates_keeps_unique_digit_tokens() -> None:
    text = "Нужны позиции ab-12, AB-12 и cd34. Ещё наличие xyz без цифр не важно."
    assert extract_article_candidates(text) == ["AB12", "CD34"]


def test_extract_article_candidates_keeps_cyrillic_suffixes() -> None:
    text = "Проверьте 14.025пр. и 14.023л."
    assert extract_article_candidates(text) == ["14025ПР", "14023Л"]


def test_extract_article_candidates_handles_cyrillic_oz() -> None:
    text = "какая цена у ОЗ/700"
    assert extract_article_candidates(text) == ["ОЗ700"]


def test_extract_article_candidates_handles_digitless_slash_article() -> None:
    text = "МП/ОЗ у него какая масса?"
    assert extract_article_candidates(text) == ["МПОЗ"]


def test_extract_article_candidates_combines_short_prefix_with_numeric_token() -> None:
    text = "МП 28ск"
    candidates = extract_article_candidates(text)
    assert "28СК" in candidates
    assert "МП28СК" in candidates


def test_extract_article_candidates_prefers_full_multiword_article() -> None:
    text = "вот таких сколько есть 7843 silk brash"
    candidates = extract_article_candidates(text)
    assert candidates[0] == "7843SILKBRASH"
    assert "7843" in candidates


def test_extract_article_candidates_compacts_split_latin_article() -> None:
    text = "а p am02 b s есть?"
    candidates = extract_article_candidates(text)
    assert candidates[0] == "PAM02BS"


def test_build_normalized_article_variants_supports_keyboard_mixed_scripts() -> None:
    assert build_normalized_article_variants("ОЗ/700") == ["ОЗ700", "OZ700"]


def test_build_normalized_article_variants_maps_mp_prefix() -> None:
    assert "MP28CK" in build_normalized_article_variants("МП 28ск")
