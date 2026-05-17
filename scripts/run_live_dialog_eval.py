from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.assistant_service import AssistantService
from database.db import create_db_and_tables, session_scope
from database.models import Message
from products.article_utils import extract_article_candidates
from settings import get_settings


@dataclass(frozen=True)
class LiveScenario:
    case_id: str
    title: str
    customer_text: str
    expected: str
    history: tuple[str, ...] = ()


DEFAULT_SCENARIOS = [
    LiveScenario("L-001", "Приветствие", "добрый день", "Живой короткий ответ менеджера без поиска товара."),
    LiveScenario("L-002", "Адрес", "Где вы находитесь?", "Адрес AMIX без поиска товара."),
    LiveScenario("L-003", "Контакты", "Как с вами связаться?", "Телефон/email AMIX без поиска товара."),
    LiveScenario("L-004", "Доставка", "Доставляете по России?", "Общий ответ про доставку без выдумывания стоимости."),
    LiveScenario("L-005", "Возврат", "Можно сделать возврат в субботу?", "Ответить, что по субботам возврат не осуществляется."),
    LiveScenario("L-006", "Точный товар", "сколько стоит 7843 silk brash", "Найти товар и ответить по цене/наличию."),
    LiveScenario("L-007", "Точный товар по коду", "проверьте код 26139", "Найти товар по коду и ответить по базе."),
    LiveScenario("L-008", "Дубли артикула", "а МП 28ск в наличии сколько", "При нескольких позициях сначала попросить уточнить код или цену."),
    LiveScenario("L-009", "Уточнение дубля", "код 26168", "Найти конкретный код и ответить по нему."),
    LiveScenario("L-010", "Точное наличие", "1108035 есть в наличии?", "Найти товар и ответить по остатку без цены, потому что клиент спросил только наличие."),
    LiveScenario("L-011", "Неточный ввод", "а p am02 b s есть?", "Не выдумывать; найти или попросить уточнение."),
    LiveScenario("L-012", "Не найдено", "Есть XYZ-999?", "Не выдумывать товар, попросить проверить артикул/код."),
    LiveScenario("L-013", "Цена без артикула", "Сколько стоит направляющая?", "Попросить артикул или код."),
    LiveScenario("L-014", "Сравнение", "Чем 14.023л. отличается от 14.023пр.?", "Не выдумывать отличия, при необходимости передать менеджеру."),
    LiveScenario("L-015", "Подбор", "Мне нужны направляющие для шкафа, что посоветуете?", "Не советовать без параметров, передать менеджеру."),
    LiveScenario("L-016", "Менеджер", "Позовите менеджера", "Передать менеджеру."),
    LiveScenario("L-017", "Заказ", "Хочу заказать 10 штук 7843 silk brash", "Проверить наличие и передать менеджеру для оформления."),
    LiveScenario("L-018", "Недостаточный остаток", "Нужно 5 штук P-AM02/B-S", "Если остатка не хватает, сказать и передать менеджеру."),
    LiveScenario("L-019", "Несколько товаров", "Проверьте 14.023пр. и 14.025пр.", "Ответить по каждому найденному товару."),
    LiveScenario("L-020", "Смешанный поиск", "Проверьте 14.023пр. и XYZ-999", "Один товар найти, второй не выдумывать."),
    LiveScenario("L-021", "Цена и отсутствие цены", "Сколько стоят 14.023пр. и P-AM02/B-S?", "Не выдумывать цену, если её нет в базе."),
    LiveScenario("L-022", "Недовольный клиент", "Вы вообще можете нормально ответить? Дайте человека", "Не спорить, передать менеджеру."),
    LiveScenario("L-023", "Дубль без лишней таблицы", "есть мп 28ск", "Несколько позиций, не выдавать таблицу, попросить код/цену/ссылку."),
    LiveScenario(
        "L-024",
        "Уточнение дубля по цене",
        "цена 132",
        "После уточнения цены выбрать подходящую позицию МП 28ск и сказать остаток.",
        history=("есть мп 28ск",),
    ),
    LiveScenario(
        "L-025",
        "Артикул со ссылкой",
        "вот ссылка на товар, артикул МП 28ск",
        "Если ссылку не парсим, попросить код или цену с карточки, не выдумывать.",
    ),
    LiveScenario(
        "L-026",
        "Сравнение из истории",
        "а чем они отличаются?",
        "Использовать историю, не выдумывать отличия, передать менеджеру.",
        history=("Проверьте 14.023л. и 14.023пр.",),
    ),
    LiveScenario(
        "L-027",
        "Менеджер после уточнения",
        "ок, давайте менеджера",
        "Сразу handoff без повторных уточнений.",
        history=("есть мп 28ск",),
    ),
    LiveScenario("L-028", "Заказ при нехватке", "Хочу заказать 5 штук P-AM02/B-S", "Не писать, что заказ можно оформить; передать менеджеру для уточнения или замены."),
    LiveScenario("L-029", "Похожий raw-запрос", "14.023", "Показать клиенту исходный запрос 14.023, а не normalized 14023."),
    LiveScenario("L-030", "Корпоративная цена", "Какая корпоративная цена у 14.025пр.?", "Учитывать настройку показа корпоративной цены и не выдумывать условия."),
    LiveScenario("L-031", "Цена отсутствует без слова выгрузка", "Сколько стоит P-AM02/B-S?", "Если цены нет, сказать живо без внутреннего слова 'выгрузка'."),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live AMIX dialog eval through the real configured LLM provider.")
    parser.add_argument("--output", default="LIVE_DIALOG_EVALS.md", help="Markdown report path.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of scenarios. 0 means all.")
    parser.add_argument("--append", action="store_true", help="Append to report instead of replacing it.")
    parser.add_argument(
        "--allow-disabled-llm",
        action="store_true",
        help="Allow fallback run if LLM provider is not configured. Default is to fail.",
    )
    args = parser.parse_args()

    create_db_and_tables()
    settings = get_settings()
    assistant = AssistantService()
    if not assistant.openai_service.enabled and not args.allow_disabled_llm:
        raise SystemExit(
            "LLM provider is not configured. Set KIE_API_KEY or OPENAI_API_KEY in .env, "
            "or pass --allow-disabled-llm for fallback-only run."
        )

    scenarios = DEFAULT_SCENARIOS[: args.limit] if args.limit else DEFAULT_SCENARIOS
    started_at = datetime.now(UTC)
    rows = []
    with session_scope() as session:
        for index, scenario in enumerate(scenarios, start=1):
            chat_id = f"live-eval:{started_at.timestamp()}:{scenario.case_id}"
            for history_index, history_text in enumerate(scenario.history, start=1):
                assistant.handle_client_message(
                    session,
                    external_chat_id=chat_id,
                    external_client_id="live-eval-user",
                    customer_name="Live Eval",
                    customer_text=history_text,
                    inbound_event_id=f"{chat_id}:history:{history_index}:in",
                    outbound_event_id=f"{chat_id}:history:{history_index}:out",
                    payload={"source": "live_dialog_eval_history", "case_id": scenario.case_id},
                    handoff_mode="demo",
                )
            inbound_event_id = f"{chat_id}:{scenario.case_id}:in"
            outbound_event_id = f"{chat_id}:{scenario.case_id}:out"
            candidates = extract_article_candidates(scenario.customer_text)
            prelookup = _prelookup(session, assistant, candidates, scenario.customer_text)

            reply = assistant.handle_client_message(
                session,
                external_chat_id=chat_id,
                external_client_id="live-eval-user",
                customer_name="Live Eval",
                customer_text=scenario.customer_text,
                inbound_event_id=inbound_event_id,
                outbound_event_id=outbound_event_id,
                payload={"source": "live_dialog_eval", "case_id": scenario.case_id},
                handoff_mode="demo",
            )
            message_payload = _get_bot_payload(session, outbound_event_id)
            rows.append(
                {
                    "case": scenario,
                    "answer": reply.text,
                    "handoff_reason": reply.handoff_reason,
                    "candidates": candidates,
                    "prelookup": prelookup,
                    "message_payload": message_payload,
                    "style_flags": _style_flags(reply.text),
                    "content_flags": _content_flags(scenario, reply.text, message_payload),
                    "manager_score": _manager_score(reply.text),
                }
            )

    output_path = Path(args.output)
    _write_report(
        output_path=output_path,
        append=args.append,
        started_at=started_at,
        provider=assistant.openai_service.provider,
        model=_model_label(assistant.openai_service),
        llm_enabled=assistant.openai_service.enabled,
        rows=rows,
    )
    print(f"Live dialog eval saved to: {output_path}")
    print(f"Scenarios: {len(rows)}")


def _prelookup(session, assistant: AssistantService, candidates: list[str], customer_text: str) -> list[dict[str, Any]]:
    result = assistant._search_products_by_queries(  # noqa: SLF001
        session,
        queries=candidates,
        reason=assistant._guess_lookup_reason(customer_text),  # noqa: SLF001
        customer_text=customer_text,
    ) if candidates else None
    results = []
    for result in (result or {}).get("per_query_results", []):
        results.append(
            {
                "query": result.get("query"),
                "display_query": result.get("display_query"),
                "raw_backend_query": result.get("raw_backend_query"),
                "status": result.get("status"),
                "exact_matches_count": result.get("exact_matches_count"),
                "similar_matches_count": result.get("similar_matches_count"),
                "exact_preview": [
                    {
                        "code": item.get("code"),
                        "article": item.get("article"),
                        "stock": item.get("stock"),
                        "retail_price": item.get("retail_price"),
                    }
                    for item in result.get("exact_matches", [])[:5]
                ],
            }
        )
    return results


def _model_label(openai_service: Any) -> str:
    if getattr(openai_service, "provider", "") == "kie":
        return getattr(openai_service, "kie_chat_model_path", "")
    return getattr(openai_service, "model", "")


def _get_bot_payload(session, outbound_event_id: str) -> dict:
    message = session.query(Message).filter(Message.external_event_id == outbound_event_id).one_or_none()
    if not message:
        return {}
    return message.payload or {}


def _style_flags(answer: str) -> list[str]:
    flags = []
    lower = answer.lower()
    if any(marker in answer for marker in ("**", "__", "`")):
        flags.append("markdown_leak")
    if any(label in answer for label in ("Код:", "Свободный остаток:", "Розничная цена:", "Корпоративная цена:")):
        flags.append("dry_field_labels")
    if any(phrase in lower for phrase in ("в демо-режиме", "в рабочем режиме", "я бы передал")):
        flags.append("demo_or_internal_phrase")
    if "выгрузк" in lower:
        flags.append("internal_export_word")
    if "свяжется с вами" in lower:
        flags.append("bad_handoff_channel")
    if any(word in lower for word in ("backend", "product_lookup_result", "exact_matches", "handoff_to_manager")):
        flags.append("internal_terms")
    if len(answer) > 700:
        flags.append("too_long")
    return flags


def _content_flags(scenario: LiveScenario, answer: str, payload: dict[str, Any]) -> list[str]:
    flags = []
    lower = answer.lower()

    if re.search(r"\bкоду\d+\b", lower) or re.search(r"\bкод\d+\b", lower):
        flags.append("code_spacing")

    if scenario.case_id == "L-003":
        has_phone_or_email = any(
            value in answer
            for value in ("+7 (812) 372-66-07", "372-66-07", "market@amix.spb.ru")
        )
        if not has_phone_or_email:
            flags.append("contacts_missing")
        if "подскажите, что нужно посмотреть" in lower and not has_phone_or_email:
            flags.append("generic_greeting_instead_of_contacts")

    if scenario.case_id == "L-004":
        if "достав" not in lower or not any(word in lower for word in ("росси", "транспорт", "курьер")):
            flags.append("delivery_answer_missing")
        if "стоим" in lower and "могу уточнить" in lower and "менеджер" not in lower:
            flags.append("delivery_price_claim")

    if scenario.case_id == "L-010":
        if any(word in lower for word in ("рознич", "корпоратив", "цена", "руб")):
            flags.append("price_given_on_stock_only_request")

    if scenario.case_id in {"L-020", "L-030"}:
        if re.search(r"корпоративн\w*\s+(?:цена\s+)?335\s*руб", lower) and "335,24" not in lower and "335.24" not in lower:
            flags.append("corporate_price_rounded")
        if re.search(r"корпоративн\w*\s+(?:цена\s+)?165\s*руб", lower) and "165,98" not in lower and "165.98" not in lower:
            flags.append("corporate_price_rounded")

    if scenario.case_id == "L-024":
        if not all(value in lower for value in ("26168", "292")):
            flags.append("price_refinement_not_resolved")
        if "уточните" in lower and ("код" in lower or "цен" in lower):
            flags.append("repeat_clarification_after_price_refinement")

    if scenario.case_id == "L-031" and "выгрузк" in lower:
        flags.append("export_word_in_missing_price")

    if scenario.case_id in {"L-017", "L-018", "L-028"}:
        if "поможет оформить" in lower or "поможет с оформлением" in lower or "можно оформить" in lower:
            flags.append("shortage_sounds_orderable")
        if payload.get("backend_actions", {}).get("response_mode") == "stock_shortage_handoff":
            if not any(word in lower for word in ("уточнит возможность", "подбер", "предложит")):
                flags.append("shortage_handoff_not_explicit")

    return flags


def _manager_score(answer: str) -> str:
    flags = _style_flags(answer)
    if flags:
        return "needs_review"
    if len(answer) <= 450 and any(word in answer.lower() for word in ("нашёл", "проверил", "подскажите", "передаю", "можно")):
        return "manager_like"
    return "ok"


def _write_report(
    *,
    output_path: Path,
    append: bool,
    started_at: datetime,
    provider: str,
    model: str,
    llm_enabled: bool,
    rows: list[dict[str, Any]],
) -> None:
    mode = "a" if append else "w"
    with output_path.open(mode, encoding="utf-8") as file:
        if append:
            file.write("\n\n---\n\n")
        file.write("# Live-отчёт по диалогам AMIX-бота\n\n")
        file.write(f"Дата прогона: `{started_at.isoformat()}`\n\n")
        file.write(f"LLM provider: `{provider}`\n\n")
        file.write(f"Model: `{model}`\n\n")
        file.write(f"LLM enabled: `{llm_enabled}`\n\n")
        file.write("Важно: это live-прогон через реальную модель, поэтому ответы могут немного отличаться между запусками.\n\n")
        file.write("## Итог\n\n")
        file.write(f"- Сценариев: `{len(rows)}`.\n")
        file.write(f"- Ответов без style flags: `{sum(not row['style_flags'] for row in rows)}`.\n")
        file.write(f"- Ответов без content flags: `{sum(not row['content_flags'] for row in rows)}`.\n")
        file.write(f"- Ответов на ручную проверку: `{sum(bool(row['style_flags'] or row['content_flags']) for row in rows)}`.\n\n")

        for row in rows:
            scenario: LiveScenario = row["case"]
            file.write(f"## {scenario.case_id} — {scenario.title}\n\n")
            file.write(f"Клиент: {scenario.customer_text}\n\n")
            if scenario.history:
                file.write(f"История перед вопросом: `{json.dumps(list(scenario.history), ensure_ascii=False)}`\n\n")
            file.write(f"Что хотели проверить: {scenario.expected}\n\n")
            file.write(f"Кандидаты поиска: `{json.dumps(row['candidates'], ensure_ascii=False)}`\n\n")
            file.write("Prelookup:\n")
            file.write(f"```json\n{json.dumps(row['prelookup'], ensure_ascii=False, indent=2)}\n```\n\n")
            payload = row["message_payload"]
            file.write(
                "Backend payload: "
                f"`status={payload.get('product_lookup_status')}`, "
                f"`exact={payload.get('exact_matches_count')}`, "
                f"`similar={payload.get('similar_matches_count')}`, "
                f"`handoff={row['handoff_reason']}`\n\n"
            )
            file.write(f"Style flags: `{', '.join(row['style_flags']) or 'нет'}`\n\n")
            file.write(f"Content flags: `{', '.join(row['content_flags']) or 'нет'}`\n\n")
            file.write(f"Оценка стиля: `{row['manager_score']}`\n\n")
            file.write(f"Ответ модели:\n{row['answer']}\n\n")


if __name__ == "__main__":
    main()
