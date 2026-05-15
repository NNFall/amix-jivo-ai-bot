from products.article_utils import extract_article_candidates, normalize_article


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
