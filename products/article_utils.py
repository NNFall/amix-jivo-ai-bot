import re


ARTICLE_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9\-_/\.]{2,}")


def normalize_article(article: str) -> str:
    prepared = article.strip().upper().replace("Ё", "Е")
    return re.sub(r"[^0-9A-ZА-Я]+", "", prepared)


def extract_article_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    for raw_candidate in ARTICLE_TOKEN_RE.findall(text):
        if not any(character.isdigit() for character in raw_candidate):
            continue

        normalized = normalize_article(raw_candidate)
        if len(normalized) < 3 or normalized in seen:
            continue

        seen.add(normalized)
        candidates.append(normalized)

    return candidates
