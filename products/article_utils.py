import re


ARTICLE_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-_/\.]*")
ARTICLE_JOIN_STOPWORDS = {
    "И",
    "ИЛИ",
    "У",
    "А",
    "ОТ",
    "ПО",
    "НА",
    "В",
    "С",
    "ДЛЯ",
    "ЕСТЬ",
    "ЦЕНА",
    "ЦЕНУ",
    "НАЛИЧИЕ",
    "СКОЛЬКО",
    "ЧЕМ",
    "ШТ",
    "ШТУК",
    "ШТУКИ",
    "ШТУКУ",
    "ХОЧУ",
    "ЗАКАЗАТЬ",
    "HOW",
    "MANY",
}


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
    prepared = article.strip().upper().replace("Ё", "Е")
    return re.sub(r"[^0-9A-ZА-Я]+", "", prepared)


def build_normalized_article_variants(article: str) -> list[str]:
    normalized = normalize_article(article)
    if not normalized:
        return []

    variants = [normalized]
    cyr_to_lat = normalized.translate(CYR_TO_LAT)
    lat_to_cyr = normalized.translate(LAT_TO_CYR)

    for variant in (cyr_to_lat, lat_to_cyr):
        if variant and variant not in variants:
            variants.append(variant)

    return variants


def extract_article_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    tokens = ARTICLE_TOKEN_RE.findall(text)

    def _push(raw_value: str) -> None:
        if not any(character.isdigit() for character in raw_value):
            return

        normalized = normalize_article(raw_value)
        if len(normalized) < 3 or normalized in seen:
            return

        seen.add(normalized)
        candidates.append(normalized)

    for start, raw_candidate in enumerate(tokens):
        normalized_first = normalize_article(raw_candidate)
        if not normalized_first or normalized_first in ARTICLE_JOIN_STOPWORDS:
            continue
        if not any(character.isdigit() for character in normalized_first) and not re.search(r"[A-Z]", normalized_first):
            continue

        phrase_tokens = [raw_candidate]
        for next_token in tokens[start + 1 : start + 5]:
            normalized_next = normalize_article(next_token)
            if not normalized_next or normalized_next in ARTICLE_JOIN_STOPWORDS:
                break
            if not re.fullmatch(r"[0-9A-Z]+", normalized_next):
                break
            if any(character.isdigit() for character in normalized_next) and any(
                character.isdigit() for token in phrase_tokens for character in normalize_article(token)
            ):
                break
            if len(normalized_next) > 12:
                break
            phrase_tokens.append(next_token)

        if len(phrase_tokens) > 1:
            _push("".join(phrase_tokens))

    # Full article names can contain spaces: "7843 silk brash".
    # Keep this narrow: one numeric token followed by article words, without connectors.
    for start, raw_candidate in enumerate(tokens):
        if not any(character.isdigit() for character in raw_candidate):
            continue

        phrase_tokens = [raw_candidate]
        for next_token in tokens[start + 1 : start + 4]:
            normalized_next = normalize_article(next_token)
            if not normalized_next or normalized_next in ARTICLE_JOIN_STOPWORDS:
                break
            if not re.fullmatch(r"[A-Z]+", normalized_next):
                break
            if any(character.isdigit() for character in normalized_next):
                break
            if len(normalized_next) < 2:
                break
            phrase_tokens.append(next_token)

        if len(phrase_tokens) > 1:
            _push("".join(phrase_tokens))

    for index, raw_candidate in enumerate(tokens):
        _push(raw_candidate)

        if index == 0:
            continue

        previous = tokens[index - 1]
        if any(character.isdigit() for character in previous):
            continue

        previous_normalized = normalize_article(previous)
        current_normalized = normalize_article(raw_candidate)
        if not previous_normalized or not current_normalized:
            continue
        if previous_normalized in ARTICLE_JOIN_STOPWORDS:
            continue

        if len(previous_normalized) < 2 or len(previous_normalized) > 4:
            continue

        _push(f"{previous_normalized}{current_normalized}")

    return candidates
