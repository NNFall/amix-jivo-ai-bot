def trim_text(value: str, limit: int = 2000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."
