from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT_DIR / "scripts" / "run_history_order_eval.py"
SCENARIOS_PATH = ROOT_DIR / "tests" / "history_order_eval_scenarios.json"
ALLOWED_TOOLS = {"search_products", "handoff_to_manager"}
REQUIRED_COVERAGE = {
    "multiple_products_different_quantities",
    "free_description_without_code",
    "correction",
    "delivery",
    "pickup",
    "invoice_payment_with_inn",
    "ambiguous_product",
    "missing_product",
    "cancel_or_topic_change",
    "confirmation_and_handoff",
}
LEGACY_ORDER_STATE_MARKERS = ("update_order_draft", "get_order_draft", "order_draft")


def test_fake_cli_writes_reproducible_private_evidence(tmp_path: Path) -> None:
    assert RUNNER_PATH.exists(), "history order eval runner is not implemented"

    output_path = tmp_path / "history-order-evidence.json"
    markdown_path = tmp_path / "history-order-report.md"
    env = os.environ.copy()
    env.pop("GOOGLE_AI_API_KEY", None)
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER_PATH),
            "--fake",
            "--scenarios",
            str(SCENARIOS_PATH),
            "--output",
            str(output_path),
            "--markdown-output",
            str(markdown_path),
            "--repeat",
            "2",
        ],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    evidence = json.loads(output_path.read_text(encoding="utf-8"))

    manifest = evidence["manifest"]
    assert manifest["git_sha"]
    assert manifest["provider"] == "fake"
    assert manifest["model"] == "fake-history-order-eval-v1"
    assert manifest["timestamp"].endswith("Z")
    assert manifest["isolated_sqlite"] is True
    assert manifest["jivo_delivery_enabled"] is False
    assert manifest["repeat"] == 2
    assert set(manifest["sha256"]) == {"prompt", "tools", "scenarios", "catalog"}
    assert all(len(value) == 64 for value in manifest["sha256"].values())
    assert set(manifest["tool_names"]) == ALLOWED_TOOLS

    scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    covered = {tag for scenario in scenarios for tag in scenario["covers"]}
    assert REQUIRED_COVERAGE <= covered
    assert len(evidence["scenarios"]) == len(scenarios) * 2
    assert evidence["summary"]["scenarios"] == len(scenarios) * 2
    assert evidence["summary"]["verdict"] == "PASS"
    assert {scenario["repetition"] for scenario in evidence["scenarios"]} == {1, 2}
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "History-driven order evaluation" in markdown
    assert "PASS" in markdown

    all_function_names: set[str] = set()
    serialized_visible_evidence: list[str] = []
    for scenario in evidence["scenarios"]:
        assert scenario["verdict"] == "PASS"
        assert scenario["turns"]
        for turn in scenario["turns"]:
            assert {
                "index",
                "input",
                "response",
                "function_calls",
                "function_results",
                "latency_ms",
                "llm_calls",
                "usage",
                "cost",
                "assertions",
                "verdict",
            } <= set(turn)
            assert turn["latency_ms"] >= 0
            assert set(turn["usage"]) == {
                "prompt_tokens",
                "completion_tokens",
                "thinking_tokens",
                "total_tokens",
            }
            assert set(turn["cost"]) == {"estimated_usd", "estimated_rub"}
            assert turn["assertions"]
            assert turn["verdict"] == "PASS"
            assert all(item["passed"] for item in turn["assertions"])
            all_function_names.update(call["name"] for call in turn["function_calls"])
            serialized_visible_evidence.extend(
                [
                    turn["response"],
                    json.dumps(turn["function_results"], ensure_ascii=False, sort_keys=True),
                ]
            )

    assert all_function_names == ALLOWED_TOOLS
    visible_text = "\n".join(serialized_visible_evidence).lower()
    for exact_stock in ("37 шт", "23 шт", "61 шт", "19 шт", "43 шт"):
        assert exact_stock not in visible_text
    assert "free_stock" not in visible_text
    assert "raw_product_lookup_result" not in visible_text


def test_eval_files_do_not_reference_legacy_order_state() -> None:
    paths = [
        RUNNER_PATH,
        ROOT_DIR / "scripts" / "run_dialog_regression_eval.py",
        ROOT_DIR / "tests" / "dialog_eval_cases.json",
        SCENARIOS_PATH,
    ]
    for path in paths:
        assert path.exists(), f"missing eval file: {path}"
        text = path.read_text(encoding="utf-8").lower()
        for marker in LEGACY_ORDER_STATE_MARKERS:
            assert marker not in text, f"legacy state marker {marker!r} remains in {path}"
