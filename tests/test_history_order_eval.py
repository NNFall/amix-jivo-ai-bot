from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import run_history_order_eval as eval_runner


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
    "missing_description_continues_order",
    "mixed_availability",
    "correction_after_summary",
    "premature_confirmation",
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
    assert manifest["mode"] == "deterministic_wiring_only"
    assert isinstance(manifest["git_dirty_files"], list)
    assert set(manifest["sha256"]) == {
        "prompt",
        "tools",
        "scenarios",
        "catalog",
        "runner",
        "assistant_service",
        "dialog_service",
        "openai_client",
    }
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
        customer_inputs: list[str] = []
        for turn in scenario["turns"]:
            customer_inputs.append(turn["input"])
            assert {
                "index",
                "input",
                "response",
                "function_calls",
                "function_results",
                "provider_requests",
                "latency_ms",
                "llm_calls",
                "usage",
                "cost",
                "assertions",
                "verdict",
            } <= set(turn)
            assert turn["latency_ms"] >= 0
            assert turn["provider_requests"]
            assert all(request["result"]["status"] == "ok" for request in turn["provider_requests"])
            first_request_text = json.dumps(
                turn["provider_requests"][0]["messages"],
                ensure_ascii=False,
            )
            assert all(customer_input in first_request_text for customer_input in customer_inputs)
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
                    json.dumps(turn["function_calls"], ensure_ascii=False, sort_keys=True),
                    json.dumps(turn["function_results"], ensure_ascii=False, sort_keys=True),
                ]
            )

    assert all_function_names == ALLOWED_TOOLS
    visible_text = "\n".join(serialized_visible_evidence).lower()
    for exact_stock in ("37 шт", "23 шт", "61 шт", "19 шт", "43 шт", "31 шт"):
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


def test_every_order_handoff_scenario_asserts_complete_summary() -> None:
    scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    handoff_turns = []
    for scenario in scenarios:
        for turn in scenario["turns"]:
            calls = (turn.get("fake") or {}).get("tool_calls") or []
            if any(
                call.get("name") == "handoff_to_manager"
                and (call.get("arguments") or {}).get("reason") == "order_creation"
                for call in calls
            ):
                handoff_turns.append((scenario["id"], turn))

    assert handoff_turns
    for scenario_id, turn in handoff_turns:
        summary_assertions = [
            assertion
            for assertion in turn.get("assertions") or []
            if assertion.get("type") == "handoff_summary_contains_all"
        ]
        assert summary_assertions, f"{scenario_id} does not verify the manager summary"
        assert len(summary_assertions[0].get("values") or []) >= 3


def test_quantity_correction_scenario_rechecks_the_latest_quantity() -> None:
    scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    scenario = next(item for item in scenarios if item["id"] == "multi_item_order_from_history")
    correction_turn = next(turn for turn in scenario["turns"] if "правых нужно 7" in turn["input"])
    calls = (correction_turn.get("fake") or {}).get("tool_calls") or []
    search_call = next(call for call in calls if call.get("name") == "search_products")
    queries = (search_call.get("arguments") or {}).get("queries") or []

    assert queries == [{"query": "14.023пр.", "requested_quantity": 7}]
    assert any(
        assertion.get("type") == "tool_query_quantities"
        and assertion.get("queries") == queries
        for assertion in correction_turn.get("assertions") or []
    )


@pytest.mark.parametrize(
    "assertion",
    [
        {"type": "unknown_check", "value": "x"},
        {"type": "response_contains", "value": ""},
        {"type": "response_contains_all", "values": []},
        {"type": "tool_called", "name": ""},
    ],
)
def test_scenario_loader_rejects_unknown_or_empty_assertions(tmp_path: Path, assertion: dict) -> None:
    scenarios_path = tmp_path / "scenarios.json"
    scenarios_path.write_text(
        json.dumps(
            [
                {
                    "id": "invalid_assertion",
                    "turns": [
                        {
                            "input": "test",
                            "fake": {"response": "test"},
                            "assertions": [assertion],
                        }
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="assertion"):
        eval_runner._load_scenarios(scenarios_path)


def test_tool_query_quantities_assertion_checks_each_product_in_order() -> None:
    turn = {
        "response": "",
        "function_results": [],
        "function_calls": [
            {
                "name": "search_products",
                "arguments": {
                    "queries": [
                        {"query": "14.023л.", "requested_quantity": 2},
                        {"query": "14.023пр.", "requested_quantity": 7},
                    ]
                },
            }
        ],
    }

    passed = eval_runner._assertion_result(
        {
            "type": "tool_query_quantities",
            "queries": [
                {"query": "14.023л.", "requested_quantity": 2},
                {"query": "14.023пр.", "requested_quantity": 7},
            ],
        },
        turn,
        None,
    )
    failed = eval_runner._assertion_result(
        {
            "type": "tool_query_quantities",
            "queries": [{"query": "14.023пр.", "requested_quantity": 5}],
        },
        turn,
        None,
    )

    assert passed["passed"] is True
    assert failed["passed"] is False


def test_handoff_summary_assertion_requires_all_latest_order_facts() -> None:
    turn = {
        "response": "Передаю менеджеру.",
        "function_results": [],
        "function_calls": [
            {
                "name": "handoff_to_manager",
                "arguments": {
                    "reason": "order_creation",
                    "summary": (
                        "Подтверждено: 2 шт. 14.023л., 7 шт. 14.023пр., самовывоз, "
                        "ИНН 7812345678, Иван, +7 900 123-45-67."
                    ),
                },
            }
        ],
    }

    assertion = eval_runner._assertion_result(
        {
            "type": "handoff_summary_contains_all",
            "values": ["2", "14.023л", "7", "14.023пр", "самовывоз", "7812345678", "Иван"],
        },
        turn,
        "order_creation",
    )

    assert assertion["passed"] is True


def test_no_handoff_assertion_accepts_a_rejected_handoff_tool_call() -> None:
    turn = {
        "response": "Проверьте итог.",
        "function_calls": [{"name": "handoff_to_manager", "arguments": {}}],
        "function_results": [
            {"name": "handoff_to_manager", "result": {"status": "rejected"}}
        ],
    }

    assertion = eval_runner._assertion_result({"type": "no_handoff"}, turn, None)

    assert assertion["passed"] is True


def test_stock_privacy_scans_function_arguments_and_every_catalog_stock() -> None:
    assertion = eval_runner._privacy_assertion(
        "Передаю менеджеру.",
        [
            {
                "name": "handoff_to_manager",
                "arguments": {"summary": "По P-AM02/B-S доступно 31 шт."},
            }
        ],
        [],
    )

    assert assertion["passed"] is False
    assert "exact_stock:31" in assertion["detail"]


def test_stock_privacy_scans_exact_provider_messages() -> None:
    assertion = eval_runner._privacy_assertion(
        "Количество есть.",
        [],
        [],
        [
            {
                "messages": [
                    {"role": "tool", "content": "По товару доступно 31 шт."},
                ]
            }
        ],
    )

    assert assertion["passed"] is False
    assert "exact_stock:31" in assertion["detail"]


def test_live_provider_health_requires_successful_logged_call_and_usage() -> None:
    missing = eval_runner._provider_health_assertion(
        mode="live_model_behavior",
        provider_name="google_ai",
        provider_requests=[],
        llm_calls=[],
    )
    failed = eval_runner._provider_health_assertion(
        mode="live_model_behavior",
        provider_name="google_ai",
        provider_requests=[{"result": {"status": "provider_error"}}],
        llm_calls=[{"provider": "google_ai", "status": "provider_error", "usage": {"total_tokens": 0}}],
    )
    passed = eval_runner._provider_health_assertion(
        mode="live_model_behavior",
        provider_name="google_ai",
        provider_requests=[{"result": {"status": "ok"}}],
        llm_calls=[{"provider": "google_ai", "status": "ok", "usage": {"total_tokens": 123}}],
    )

    assert missing["passed"] is False
    assert failed["passed"] is False
    assert passed["passed"] is True
