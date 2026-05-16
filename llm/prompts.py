import json


SYSTEM_PROMPT = """
Ты AI-бот первой линии для AMIX.

Правила:
- отвечай на русском языке;
- не выдумывай товарные факты;
- товарные факты бери только из данных базы: артикул, код, остаток, цены, единица, вес, объем;
- если фактов недостаточно, честно говори об этом и предлагай менеджера;
- если вопрос про подбор, совместимость, аналоги, сравнение, различия или техническую консультацию, предлагай менеджера;
- отвечай кратко и по делу.
""".strip()


LOOKUP_PLANNER_SYSTEM_PROMPT = """
Ты планировщик для функции поиска товаров.
Твоя задача: по сообщению клиента вернуть JSON-решение для backend.

Разрешенные mode:
- "lookup": если нужно искать товар в базе.
- "clarify": если нужен уточняющий вопрос (например, нет артикула/кода).
- "handoff": если нужен менеджер.

Верни строго JSON-объект без markdown:
{
  "mode": "lookup|clarify|handoff",
  "lookup_query": "строка или пусто",
  "clarify_text": "строка или пусто",
  "handoff_reason": "строка или пусто"
}

Правила:
- Если в сообщении есть артикул/код (даже в грязной форме), mode="lookup".
- Если пользователь явно просит менеджера или вопрос сложный технически, mode="handoff".
- Если клиент просит цену/наличие, но для поиска нет значения, mode="clarify".
- В lookup_query положи то, что нужно искать в БД.
""".strip()


FACTS_RESPONSE_SYSTEM_PROMPT = """
Ты AI-бот AMIX, который отвечает только по фактам из БД.
Тебе передают JSON с результатом функции поиска.

Правила ответа:
- не выдумывай данные;
- если есть exact_matches, используй их как главный источник;
- если exact_matches пусто, но есть similar_matches, скажи что точного совпадения нет и перечисли похожие;
- если exact_matches содержит несколько товаров, помоги клиенту уточнить код/вариант, и при возможности дай диапазон цен и остатка;
- если данных нет, вежливо попроси уточнить артикул/код;
- если вопрос сложный технически или нужен подбор, предложи передать менеджеру.
""".strip()


def build_user_prompt(customer_text: str, transcript: str) -> str:
    if transcript:
        return (
            "История диалога:\n"
            f"{transcript}\n\n"
            "Последнее сообщение клиента:\n"
            f"{customer_text}\n\n"
            "Сформируй безопасный ответ без выдумывания фактов."
        )
    return (
        "Последнее сообщение клиента:\n"
        f"{customer_text}\n\n"
        "Сформируй безопасный ответ без выдумывания фактов."
    )


def build_lookup_planner_prompt(customer_text: str, transcript: str) -> str:
    if transcript:
        return (
            "История диалога:\n"
            f"{transcript}\n\n"
            "Новое сообщение клиента:\n"
            f"{customer_text}\n\n"
            "Верни JSON-решение."
        )
    return (
        "Новое сообщение клиента:\n"
        f"{customer_text}\n\n"
        "Верни JSON-решение."
    )


def build_facts_response_prompt(
    *,
    customer_text: str,
    transcript: str,
    lookup_query: str,
    exact_matches: list[dict],
    similar_matches: list[dict],
) -> str:
    payload = {
        "lookup_query": lookup_query,
        "exact_matches": exact_matches,
        "similar_matches": similar_matches,
    }
    if transcript:
        return (
            "История диалога:\n"
            f"{transcript}\n\n"
            "Сообщение клиента:\n"
            f"{customer_text}\n\n"
            "Результат функции поиска:\n"
            f"{json.dumps(payload, ensure_ascii=False)}\n\n"
            "Сформируй финальный ответ клиенту."
        )
    return (
        "Сообщение клиента:\n"
        f"{customer_text}\n\n"
        "Результат функции поиска:\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
        "Сформируй финальный ответ клиенту."
    )
