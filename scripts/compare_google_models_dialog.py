from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.assistant_service import AssistantService
from database.db import create_db_and_tables, session_scope
from database.models import Message
from llm.openai_client import OpenAIService
from settings import get_settings


DEFAULT_MODELS = [
    "gemini-3-flash-preview",
    "gemini-2.5-pro",
    "gemini-3.1-flash-lite",
]

DEFAULT_DIALOG = [
    "нужно наличие узнать 14.023пр и p am02 b s",
    "а по второму сколько осталось именно?",
    "сколько стоит 14.023пр",
    "а есть мп 28ск",
    "198 которая",
    "а дешевле мп есть?",
    "а где вы находитесь?",
    "расскажите коротко о компании",
    "а 14.023 без пр есть?",
    "чем л отличается от пр?",
]


@dataclass(slots=True)
class TurnReport:
    index: int
    user_text: str
    bot_text: str
    source: str | None
    lookup_status: str | None
    handoff_reason: str | None
    wall_ms: int
    provider_attempts: int
    http_statuses: list[int | None]
    error_types: list[str | None]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_rub: float


@dataclass(slots=True)
class ModelReport:
    model: str
    status: str
    error: str | None
    turns: list[TurnReport]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Google AI Studio models on the same AMIX dialog.")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS), help="Comma-separated model ids.")
    parser.add_argument("--output", default="MODEL_COMPARE_REPORT.md", help="Markdown report path.")
    parser.add_argument("--json-output", default="MODEL_COMPARE_REPORT.json", help="Raw JSON report path.")
    parser.add_argument("--min-interval", type=float, default=1.0, help="Per-process throttle for this comparison run.")
    parser.add_argument("--rate-limit-delay", type=float, default=20.0, help="Delay after 429 for this comparison run.")
    parser.add_argument("--retry-attempts", type=int, default=2, help="Retry attempts for this comparison run.")
    parser.add_argument("--usd-to-rub", type=float, default=None, help="Override RUB conversion for report.")
    args = parser.parse_args()

    models = [model.strip() for model in args.models.split(",") if model.strip()]
    if not models:
        raise SystemExit("No models provided.")

    output_path = Path(args.output)
    json_output_path = Path(args.json_output)
    started_at = datetime.now(UTC)

    create_db_and_tables()
    reports: list[ModelReport] = []
    for model in models:
        reports.append(
            run_model_dialog(
                model=model,
                min_interval=args.min_interval,
                rate_limit_delay=args.rate_limit_delay,
                retry_attempts=args.retry_attempts,
                usd_to_rub=args.usd_to_rub,
                started_at=started_at,
            )
        )

    write_markdown_report(output_path=output_path, started_at=started_at, reports=reports)
    write_json_report(json_output_path=json_output_path, started_at=started_at, reports=reports)
    print(f"Model comparison saved to: {output_path}")
    print(f"Raw JSON saved to: {json_output_path}")
    return 0


def run_model_dialog(
    *,
    model: str,
    min_interval: float,
    rate_limit_delay: float,
    retry_attempts: int,
    usd_to_rub: float | None,
    started_at: datetime,
) -> ModelReport:
    os.environ["LLM_PROVIDER"] = "google_ai_studio"
    os.environ["GOOGLE_AI_MODEL"] = model
    os.environ["GOOGLE_AI_MIN_REQUEST_INTERVAL_SECONDS"] = str(min_interval)
    os.environ["GOOGLE_AI_RATE_LIMIT_RETRY_DELAY_SECONDS"] = str(rate_limit_delay)
    os.environ["GOOGLE_AI_RETRY_MAX_ATTEMPTS"] = str(max(1, retry_attempts))
    if usd_to_rub is not None:
        os.environ["LLM_COST_USD_TO_RUB"] = str(usd_to_rub)

    get_settings.cache_clear()
    OpenAIService._provider_last_request_at.clear()
    settings = get_settings()
    audit_path = Path(settings.llm_audit_log_path)
    assistant = AssistantService()
    chat_id = f"model-compare:{started_at.strftime('%Y%m%d%H%M%S')}:{safe_name(model)}"
    turns: list[TurnReport] = []

    with session_scope() as session:
        for index, user_text in enumerate(DEFAULT_DIALOG, start=1):
            turn_started_at = datetime.now(UTC)
            wall_started = time.monotonic()
            try:
                reply = assistant.handle_client_message(
                    session,
                    external_chat_id=chat_id,
                    external_client_id=f"model-compare-user:{safe_name(model)}",
                    customer_name="Model Compare",
                    customer_text=user_text,
                    inbound_event_id=f"{chat_id}:in:{index}",
                    outbound_event_id=f"{chat_id}:out:{index}",
                    payload={"source": "model_compare", "model": model, "turn": index},
                    handoff_mode="demo",
                )
            except Exception as exc:  # pragma: no cover - manual script path
                return ModelReport(model=model, status="failed", error=repr(exc), turns=turns)
            wall_ms = int((time.monotonic() - wall_started) * 1000)
            audit_entries = read_audit_entries_since(audit_path, since=turn_started_at, model=model)
            message_payload = get_bot_payload(session, f"{chat_id}:out:{index}")
            turns.append(
                TurnReport(
                    index=index,
                    user_text=user_text,
                    bot_text=reply.text,
                    source=message_payload.get("source") or message_payload.get("payload_source"),
                    lookup_status=message_payload.get("product_lookup_status"),
                    handoff_reason=reply.handoff_reason,
                    wall_ms=wall_ms,
                    provider_attempts=len(audit_entries),
                    http_statuses=[entry.get("http_status") for entry in audit_entries],
                    error_types=[
                        ((entry.get("error") or {}).get("type") if isinstance(entry.get("error"), dict) else None)
                        for entry in audit_entries
                    ],
                    prompt_tokens=sum_int(audit_entries, "usage", "prompt_tokens"),
                    completion_tokens=sum_int(audit_entries, "usage", "completion_tokens"),
                    total_tokens=sum_int(audit_entries, "usage", "total_tokens"),
                    estimated_rub=sum_float(audit_entries, "cost", "estimated_rub"),
                )
            )

    return ModelReport(model=model, status="ok", error=None, turns=turns)


def get_bot_payload(session, outbound_event_id: str) -> dict[str, Any]:
    message = session.query(Message).filter(Message.external_event_id == outbound_event_id).one_or_none()
    if message is None:
        return {}
    return message.payload or {}


def read_audit_entries_since(path: Path, *, since: datetime, model: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    entries = payload.get("entries") or []
    result: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("model") != model:
            continue
        timestamp = parse_datetime(entry.get("timestamp"))
        if timestamp is None or timestamp < since:
            continue
        result.append(entry)
    return result


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def sum_int(entries: list[dict[str, Any]], section: str, key: str) -> int:
    total = 0
    for entry in entries:
        value = (entry.get(section) or {}).get(key)
        if value is None:
            continue
        total += int(value)
    return total


def sum_float(entries: list[dict[str, Any]], section: str, key: str) -> float:
    total = 0.0
    for entry in entries:
        value = (entry.get(section) or {}).get(key)
        if value is None:
            continue
        total += float(value)
    return round(total, 4)


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)


def write_markdown_report(*, output_path: Path, started_at: datetime, reports: list[ModelReport]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        file.write("# Сравнение Google Gemini моделей на AMIX-диалоге\n\n")
        file.write(f"Дата прогона: `{started_at.isoformat()}`\n\n")
        file.write("## Тестовый диалог\n\n")
        for index, text in enumerate(DEFAULT_DIALOG, start=1):
            file.write(f"{index}. Клиент: {text}\n")
        file.write("\n")
        file.write("## Сводка\n\n")
        file.write("| Модель | Статус | Запросов к LLM | Ошибки HTTP | Время всего | Токены | Стоимость, руб |\n")
        file.write("|---|---:|---:|---|---:|---:|---:|\n")
        for report in reports:
            turns = report.turns
            http_errors = [
                status
                for turn in turns
                for status in turn.http_statuses
                if status and status >= 400
            ]
            file.write(
                "| "
                + " | ".join(
                    [
                        f"`{report.model}`",
                        report.status,
                        str(sum(turn.provider_attempts for turn in turns)),
                        ", ".join(str(status) for status in http_errors) or "нет",
                        f"{sum(turn.wall_ms for turn in turns) / 1000:.1f} c",
                        str(sum(turn.total_tokens for turn in turns)),
                        f"{sum(turn.estimated_rub for turn in turns):.4f}",
                    ]
                )
                + " |\n"
            )
        file.write("\n")
        for report in reports:
            file.write(f"## Модель `{report.model}`\n\n")
            if report.error:
                file.write(f"Ошибка: `{report.error}`\n\n")
            for turn in report.turns:
                file.write(f"### {turn.index}. {turn.user_text}\n\n")
                file.write(
                    f"- Источник: `{turn.source}`; lookup: `{turn.lookup_status}`; "
                    f"handoff: `{turn.handoff_reason}`\n"
                )
                file.write(
                    f"- LLM: attempts `{turn.provider_attempts}`, http `{turn.http_statuses}`, "
                    f"time `{turn.wall_ms / 1000:.2f}s`, tokens `{turn.total_tokens}`, "
                    f"cost `{turn.estimated_rub:.4f} руб.`\n\n"
                )
                file.write(f"Ответ:\n{turn.bot_text}\n\n")


def write_json_report(*, json_output_path: Path, started_at: datetime, reports: list[ModelReport]) -> None:
    json_output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "started_at": started_at.isoformat(),
        "dialog": DEFAULT_DIALOG,
        "reports": [
            {
                "model": report.model,
                "status": report.status,
                "error": report.error,
                "turns": [
                    {
                        "index": turn.index,
                        "user_text": turn.user_text,
                        "bot_text": turn.bot_text,
                        "source": turn.source,
                        "lookup_status": turn.lookup_status,
                        "handoff_reason": turn.handoff_reason,
                        "wall_ms": turn.wall_ms,
                        "provider_attempts": turn.provider_attempts,
                        "http_statuses": turn.http_statuses,
                        "error_types": turn.error_types,
                        "prompt_tokens": turn.prompt_tokens,
                        "completion_tokens": turn.completion_tokens,
                        "total_tokens": turn.total_tokens,
                        "estimated_rub": turn.estimated_rub,
                    }
                    for turn in report.turns
                ],
            }
            for report in reports
        ],
    }
    json_output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
