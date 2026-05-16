from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.assistant_service import AssistantService
from database.db import create_db_and_tables, session_scope
from database.repositories import search_products_structured
from llm import prompts as llm_prompts
from llm.tool_schemas import OPENAI_TOOLS
from products.article_utils import extract_article_candidates


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
}


def _prompt_fingerprint() -> str:
    payload = "\n".join(
        [
            llm_prompts.SYSTEM_PROMPT,
            llm_prompts.PRODUCT_FACTS_RESPONSE_PROMPT,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _append_markdown_report(
    *,
    output_path: Path,
    started_at: datetime,
    scenario_name: str,
    provider: str,
    model: str,
    prompt_fingerprint: str,
    turns: list[dict[str, Any]],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as fp:
        fp.write(f"\n## Run {started_at.isoformat()}\n\n")
        fp.write(f"- Scenario: `{scenario_name}`\n")
        fp.write(f"- Provider: `{provider}`\n")
        fp.write(f"- Model: `{model}`\n")
        fp.write(f"- Prompt fingerprint: `{prompt_fingerprint}`\n\n")

        for index, turn in enumerate(turns, start=1):
            fp.write(f"### Turn {index}\n")
            fp.write(f"- Client: {turn['client_text']}\n")
            fp.write(f"- Planner mode: `{turn['planner_mode']}`\n")

            if turn["planner_raw"] is not None:
                fp.write("- Planner raw:\n")
                fp.write("```json\n")
                fp.write(json.dumps(turn["planner_raw"], ensure_ascii=False, indent=2))
                fp.write("\n```\n")
            else:
                fp.write("- Planner raw: `null`\n")

            if turn["lookup"] is not None:
                fp.write("- Lookup call:\n")
                fp.write("```json\n")
                fp.write(json.dumps(turn["lookup"], ensure_ascii=False, indent=2))
                fp.write("\n```\n")
            else:
                fp.write("- Lookup call: `not-called`\n")

            fp.write(f"- Bot: {turn['bot_text']}\n\n")


def run_eval(*, scenario_name: str, output_path: Path) -> None:
    scenario = DEFAULT_SCENARIOS.get(scenario_name)
    if scenario is None:
        raise ValueError(f"Unknown scenario: {scenario_name}. Available: {', '.join(DEFAULT_SCENARIOS)}")

    create_db_and_tables()
    assistant = AssistantService()
    started_at = datetime.now(UTC)
    external_chat_id = f"dialog-eval:{started_at.strftime('%Y%m%d%H%M%S')}"
    external_client_id = "dialog-eval-user"
    turns: list[dict[str, Any]] = []

    with session_scope() as session:
        for index, text in enumerate(scenario, start=1):
            transcript = assistant.dialog_service.get_transcript(session, external_chat_id)
            tool_calls: list[dict] = []
            lookup_report = None
            planner_mode = "disabled"

            if assistant.openai_service.enabled:
                candidates = extract_article_candidates(text)
                if candidates:
                    planner_mode = "backend_prelookup"
                    lookup_report = search_products_structured(session, query=candidates[0], search_type="auto")
                else:
                    messages = llm_prompts.build_llm_messages(
                        transcript=transcript,
                        customer_text=text,
                        product_lookup_result=None,
                    )
                    turn = assistant.openai_service.run_messages(messages=messages, tools=OPENAI_TOOLS, tool_choice="auto")
                    planner_mode = "tools_auto"
                    tool_calls = [{"name": call.name, "arguments": call.arguments} for call in turn.tool_calls]

            reply = assistant.handle_client_message(
                session,
                external_chat_id=external_chat_id,
                external_client_id=external_client_id,
                customer_name="Dialog Eval",
                customer_text=text,
                inbound_event_id=f"dialog-eval:{started_at.strftime('%Y%m%d%H%M%S')}:{index}",
                outbound_event_id=f"dialog-eval:{started_at.strftime('%Y%m%d%H%M%S')}:{index}:bot",
                payload={"source": "dialog_eval_script", "scenario": scenario_name},
                handoff_mode="demo",
            )

            turns.append(
                {
                    "client_text": text,
                    "planner_raw": tool_calls or None,
                    "planner_mode": planner_mode,
                    "lookup": lookup_report,
                    "bot_text": reply.text,
                }
            )

    provider = assistant.openai_service.provider
    model = assistant.openai_service.model if provider == "openai" else assistant.openai_service.kie_chat_model_path
    _append_markdown_report(
        output_path=output_path,
        started_at=started_at,
        scenario_name=scenario_name,
        provider=provider,
        model=model,
        prompt_fingerprint=_prompt_fingerprint(),
        turns=turns,
    )

    print(f"Dialog eval saved to: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a dialog scenario and append report to markdown.")
    parser.add_argument("--scenario", default="smoke", choices=sorted(DEFAULT_SCENARIOS.keys()))
    parser.add_argument("--output", default="DIALOG_EVALS.md")
    args = parser.parse_args()

    run_eval(scenario_name=args.scenario, output_path=Path(args.output))


if __name__ == "__main__":
    main()
