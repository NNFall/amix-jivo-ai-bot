from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.assistant_service import AssistantService
from database.db import create_db_and_tables, session_scope
from database.models import Message


ALLOWED_TOOLS = {"search_products", "handoff_to_manager"}


@dataclass(frozen=True)
class LiveScenario:
    case_id: str
    title: str
    customer_text: str
    expected: str
    history: tuple[str, ...] = ()


DEFAULT_SCENARIOS = [
    LiveScenario("L-001", "Адрес", "Где вы находитесь?", "Ответ по справке без функции."),
    LiveScenario("L-002", "Контакты", "Как с вами связаться?", "Телефон и email без функции."),
    LiveScenario("L-003", "Наличие без количества", "14.023пр есть?", "Спросить нужное количество."),
    LiveScenario(
        "L-004",
        "Продолжение наличия",
        "две штуки",
        "Проверить количество и ответить да или нет.",
        history=("14.023пр есть?",),
    ),
    LiveScenario(
        "L-005",
        "Два товара",
        "Нужно 2 штуки первого и 3 штуки второго",
        "Сохранить порядок и проверить оба количества.",
        history=("Проверьте 14.023пр и P-AM02/B-S",),
    ),
    LiveScenario(
        "L-006",
        "Исправление",
        "нет, второго нужно 4 штуки",
        "Заменить количество второго товара и проверить его заново.",
        history=(
            "Хочу заказать 2 штуки 14.023пр и 3 штуки P-AM02/B-S",
            "Доставка в Тверь",
        ),
    ),
    LiveScenario("L-007", "Не найдено", "Есть XYZ-999?", "Не выдумывать товар."),
    LiveScenario(
        "L-008",
        "Технический подбор",
        "Подойдёт ли эта деталь к моему шкафу?",
        "Передать менеджеру.",
        history=("Артикул 14.023пр",),
    ),
    LiveScenario("L-009", "Просьба человека", "Позовите менеджера", "Передать менеджеру."),
    LiveScenario(
        "L-010",
        "Сбор заказа",
        "Никита, +7 900 000-00-00, ИНН 1234567890",
        "Показать полный итог и запросить подтверждение без преждевременной передачи.",
        history=(
            "Мне нужно оформить заказ",
            "Код 770 — 2 штуки и код 28834 — 3 штуки",
            "Доставка в Тверь на следующей неделе",
            "Оплата по счёту",
        ),
    ),
    LiveScenario(
        "L-011",
        "Подтверждение заказа",
        "Да, всё верно",
        "Передать менеджеру с полным резюме.",
        history=(
            "Хочу заказать код 770 — 2 штуки",
            "Доставка в Тверь на следующей неделе, оплата по счёту",
            "Никита, +7 900 000-00-00, ИНН 1234567890",
            "Итого: код 770 — 2 штуки, доставка в Тверь на следующей неделе, оплата по счёту, Никита, +7 900 000-00-00, ИНН 1234567890. Всё верно?",
        ),
    ),
]


def _model_label(assistant: AssistantService) -> str:
    provider = assistant.openai_service.provider
    if provider in {"google", "google_ai", "google_ai_studio", "gemini"}:
        return assistant.openai_service.google_ai_model
    if provider == "kie":
        return assistant.openai_service.kie_chat_model_path
    return assistant.openai_service.model


def _function_history(session, after_id: int) -> list[dict[str, Any]]:
    rows = session.query(Message).filter(Message.id > after_id).order_by(Message.id.asc()).all()
    return [
        {"role": row.sender_role, "payload": row.payload or {}}
        for row in rows
        if row.sender_role in {"assistant_tool_call", "tool"}
    ]


def _called_tool_names(function_history: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for message in function_history:
        if message.get("role") != "assistant_tool_call":
            continue
        for call in (message.get("payload") or {}).get("tool_calls") or []:
            name = str(((call or {}).get("function") or {}).get("name") or "")
            if name:
                names.append(name)
    return names


def _style_flags(answer: str) -> list[str]:
    flags: list[str] = []
    lower = answer.lower()
    if not answer.strip():
        flags.append("empty_answer")
    if any(marker in answer for marker in ("**", "__", "`")):
        flags.append("markdown_leak")
    if any(word in lower for word in ("backend", "json", "tool call", "function call")):
        flags.append("internal_terms")
    if len(answer) > 700:
        flags.append("too_long")
    return flags


def _content_flags(
    scenario: LiveScenario,
    answer: str,
    evidence: dict[str, Any],
) -> list[str]:
    del scenario
    flags: list[str] = []
    function_history = evidence.get("function_history") or []
    called_tools = _called_tool_names(function_history)
    unknown_tools = sorted(set(called_tools) - ALLOWED_TOOLS)
    if unknown_tools:
        flags.append(f"unknown_tools:{','.join(unknown_tools)}")
    lower = answer.lower()
    promises_handoff = "переда" in lower and "менеджер" in lower
    if promises_handoff and "handoff_to_manager" not in called_tools:
        flags.append("handoff_promise_without_tool")
    return flags


def _run_customer_turn(
    *,
    assistant: AssistantService,
    session,
    chat_id: str,
    case_id: str,
    index: int,
    text: str,
) -> dict[str, Any]:
    before_id = session.query(Message.id).order_by(Message.id.desc()).limit(1).scalar() or 0
    reply = assistant.handle_client_message(
        session,
        external_chat_id=chat_id,
        external_client_id="live-eval-user",
        customer_name="Live Eval",
        customer_text=text,
        inbound_event_id=f"{chat_id}:{index}:in",
        outbound_event_id=f"{chat_id}:{index}:out",
        payload={"source": "live_dialog_eval", "case_id": case_id},
        handoff_mode="demo",
    )
    session.flush()
    return {
        "client": text,
        "bot": reply.text,
        "handoff_reason": reply.handoff_reason,
        "function_history": _function_history(session, before_id),
    }


def _write_report(
    *,
    output_path: Path,
    append: bool,
    started_at: datetime,
    assistant: AssistantService,
    rows: list[dict[str, Any]],
) -> None:
    mode = "a" if append else "w"
    with output_path.open(mode, encoding="utf-8") as file:
        if append:
            file.write("\n\n---\n\n")
        file.write("# Live-отчёт по диалогам AMIX-бота\n\n")
        file.write(f"Дата: `{started_at.isoformat()}`\n\n")
        file.write(f"Provider: `{assistant.openai_service.provider}`\n\n")
        file.write(f"Model: `{_model_label(assistant)}`\n\n")
        file.write(f"Сценариев: `{len(rows)}`\n\n")
        for row in rows:
            scenario: LiveScenario = row["scenario"]
            file.write(f"## {scenario.case_id} — {scenario.title}\n\n")
            file.write(f"Ожидание: {scenario.expected}\n\n")
            for turn in row["turns"]:
                file.write(f"Клиент: {turn['client']}\n\n")
                file.write(f"Бот: {turn['bot']}\n\n")
                file.write("Функции:\n```json\n")
                file.write(json.dumps(turn["function_history"], ensure_ascii=False, indent=2))
                file.write("\n```\n\n")
            file.write(f"Flags: `{json.dumps(row['flags'], ensure_ascii=False)}`\n\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live dialogs through the real AMIX assistant.")
    parser.add_argument("--output", default="LIVE_DIALOG_EVALS.md")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--allow-disabled-llm", action="store_true")
    args = parser.parse_args()

    create_db_and_tables()
    assistant = AssistantService()
    if not assistant.openai_service.enabled and not args.allow_disabled_llm:
        raise SystemExit("LLM provider is not configured.")

    scenarios = [item for item in DEFAULT_SCENARIOS if not args.case or item.case_id in set(args.case)]
    if args.limit:
        scenarios = scenarios[: args.limit]
    started_at = datetime.now(UTC)
    rows: list[dict[str, Any]] = []

    with session_scope() as session:
        for scenario in scenarios:
            chat_id = f"live-eval:{started_at.timestamp()}:{scenario.case_id}"
            turns: list[dict[str, Any]] = []
            all_inputs = [*scenario.history, scenario.customer_text]
            for index, text in enumerate(all_inputs, start=1):
                turns.append(
                    _run_customer_turn(
                        assistant=assistant,
                        session=session,
                        chat_id=chat_id,
                        case_id=scenario.case_id,
                        index=index,
                        text=text,
                    )
                )
            final_turn = turns[-1]
            evidence = {"function_history": final_turn["function_history"]}
            flags = _style_flags(final_turn["bot"]) + _content_flags(
                scenario,
                final_turn["bot"],
                evidence,
            )
            rows.append({"scenario": scenario, "turns": turns, "flags": flags})

    _write_report(
        output_path=Path(args.output),
        append=args.append,
        started_at=started_at,
        assistant=assistant,
        rows=rows,
    )
    print(f"Live dialog eval saved to: {args.output}")
    print(f"Scenarios: {len(rows)}")


if __name__ == "__main__":
    main()
