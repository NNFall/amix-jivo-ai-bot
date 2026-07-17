from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
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
from llm.prompts import SYSTEM_PROMPT


DEFAULT_SCENARIOS: dict[str, list[str]] = {
    "smoke": [
        "добрый день",
        "я хочу цену примерную хоть узнать у 7843 silk brash",
        "а где находится ваш магазин и какой график работы?",
    ],
    "products_only": [
        "какая цена у 1108035",
        "а наличие у оз/700",
        "мп 28ск",
    ],
    "order": [
        "Мне нужно оформить заказ",
        "Код 770 — 2 штуки и код 28834 — 3 штуки",
        "Доставка в Тверь на следующей неделе, оплата по счёту",
        "Никита, +7 900 000-00-00, ИНН 1234567890",
        "Да, всё верно",
    ],
}


def _prompt_fingerprint() -> str:
    return hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


def _model_label(assistant: AssistantService) -> str:
    provider = assistant.openai_service.provider
    if provider in {"google", "google_ai", "google_ai_studio", "gemini"}:
        return assistant.openai_service.google_ai_model
    if provider == "kie":
        return assistant.openai_service.kie_chat_model_path
    return assistant.openai_service.model


def _new_internal_messages(session, after_id: int) -> list[dict[str, Any]]:
    rows = session.query(Message).filter(Message.id > after_id).order_by(Message.id.asc()).all()
    return [
        {
            "role": row.sender_role,
            "text": row.text,
            "payload": row.payload or {},
        }
        for row in rows
        if row.sender_role in {"assistant_tool_call", "tool"}
    ]


def _write_report(
    *,
    output_path: Path,
    started_at: datetime,
    scenario_name: str,
    assistant: AssistantService,
    turns: list[dict[str, Any]],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as file:
        file.write(f"\n## Run {started_at.isoformat()}\n\n")
        file.write(f"- Scenario: `{scenario_name}`\n")
        file.write(f"- Provider: `{assistant.openai_service.provider}`\n")
        file.write(f"- Model: `{_model_label(assistant)}`\n")
        file.write(f"- Prompt fingerprint: `{_prompt_fingerprint()}`\n\n")
        for index, turn in enumerate(turns, start=1):
            file.write(f"### Turn {index}\n")
            file.write(f"- Client: {turn['client_text']}\n")
            file.write(f"- Bot: {turn['bot_text']}\n")
            file.write("- Function history:\n```json\n")
            file.write(json.dumps(turn["function_history"], ensure_ascii=False, indent=2))
            file.write("\n```\n\n")


def run_eval(*, scenario_name: str, output_path: Path) -> None:
    scenario = DEFAULT_SCENARIOS.get(scenario_name)
    if scenario is None:
        raise ValueError(f"Unknown scenario: {scenario_name}. Available: {', '.join(DEFAULT_SCENARIOS)}")

    create_db_and_tables()
    assistant = AssistantService()
    started_at = datetime.now(UTC)
    external_chat_id = f"dialog-eval:{started_at.strftime('%Y%m%d%H%M%S%f')}"
    turns: list[dict[str, Any]] = []

    with session_scope() as session:
        for index, text in enumerate(scenario, start=1):
            before_id = session.query(Message.id).order_by(Message.id.desc()).limit(1).scalar() or 0
            reply = assistant.handle_client_message(
                session,
                external_chat_id=external_chat_id,
                external_client_id="dialog-eval-user",
                customer_name="Dialog Eval",
                customer_text=text,
                inbound_event_id=f"{external_chat_id}:in:{index}",
                outbound_event_id=f"{external_chat_id}:out:{index}",
                payload={"source": "dialog_eval_script", "scenario": scenario_name},
                handoff_mode="demo",
            )
            session.flush()
            turns.append(
                {
                    "client_text": text,
                    "bot_text": reply.text,
                    "function_history": _new_internal_messages(session, before_id),
                }
            )

    _write_report(
        output_path=output_path,
        started_at=started_at,
        scenario_name=scenario_name,
        assistant=assistant,
        turns=turns,
    )
    print(f"Dialog eval saved to: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a dialog through the real assistant pipeline.")
    parser.add_argument("--scenario", default="smoke", choices=sorted(DEFAULT_SCENARIOS))
    parser.add_argument("--output", default="DIALOG_EVALS.md")
    args = parser.parse_args()
    run_eval(scenario_name=args.scenario, output_path=Path(args.output))


if __name__ == "__main__":
    main()
