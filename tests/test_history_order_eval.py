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


def test_fake_provider_rejects_arguments_outside_production_tool_schema() -> None:
    provider = eval_runner.FakeTurnProvider()
    provider.start_turn(
        "invalid-schema",
        1,
        {
            "fake": {
                "tool_calls": [
                    {
                        "name": "search_products",
                        "arguments": {"queries": [], "legacy_route": True},
                    }
                ]
            }
        },
    )

    with pytest.raises(ValueError, match="schema"):
        provider(messages=[], tools=eval_runner.OPENAI_TOOLS)


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
    serialized_customer_evidence: list[str] = []
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
            serialized_customer_evidence.extend(
                [
                    turn["response"],
                    json.dumps(turn["function_calls"], ensure_ascii=False, sort_keys=True),
                ]
            )

    assert all_function_names == ALLOWED_TOOLS
    visible_text = "\n".join(serialized_customer_evidence).lower()
    for exact_stock in ("37 шт", "23 шт", "61 шт", "19 шт", "43 шт", "31 шт"):
        assert exact_stock not in visible_text
    assert "free_stock" not in visible_text


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


@pytest.mark.parametrize(
    "relative_path",
    [
        "scripts/run_dialog_eval.py",
        "scripts/run_dialog_regression_eval.py",
        "scripts/run_live_dialog_eval.py",
    ],
)
def test_dialog_eval_scripts_do_not_preclassify_customer_language(relative_path: str) -> None:
    text = (ROOT_DIR / relative_path).read_text(encoding="utf-8")

    for marker in (
        "extract_article_candidates",
        "backend_prelookup",
        "_guess_lookup_reason",
        "_extract_requested_quantity",
        "backend_actions",
    ):
        assert marker not in text, f"semantic backend marker {marker!r} remains in {relative_path}"


def test_every_order_handoff_scenario_asserts_complete_summary() -> None:
    scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    handoff_turns = []
    for scenario in scenarios:
        for turn in scenario["turns"]:
            assertions = turn.get("assertions") or []
            if any(
                assertion.get("type") == "handoff_reason"
                and assertion.get("value") == "order_creation"
                for assertion in assertions
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
        values = summary_assertions[0].get("values") or []
        assert len(values) >= 7, f"{scenario_id} verifies too few order facts: {values!r}"
        handoff_calls = [
            call
            for call in ((turn.get("fake") or {}).get("tool_calls") or [])
            if call.get("name") == "handoff_to_manager"
        ]
        assert handoff_calls, f"{scenario_id} has no fake handoff call"
        summary = str((handoff_calls[-1].get("arguments") or {}).get("summary") or "")
        summary_lower = summary.lower()
        for value in values:
            options = value.get("any") or [] if isinstance(value, dict) else [value]
            assert any(str(option).lower() in summary_lower for option in options), (
                f"{scenario_id} fake handoff summary misses {value!r}: {summary!r}"
            )


def test_quantity_correction_scenario_rechecks_the_latest_quantity() -> None:
    scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    scenario = next(item for item in scenarios if item["id"] == "multi_item_order_from_history")
    correction_turn = next(turn for turn in scenario["turns"] if "правых нужно 7" in turn["input"])
    calls = (correction_turn.get("fake") or {}).get("tool_calls") or []
    search_call = next(call for call in calls if call.get("name") == "search_products")
    queries = (search_call.get("arguments") or {}).get("queries") or []

    assert queries == [{"query": "14.023пр.", "requested_quantity": 7}]
    assert any(
        assertion.get("type") == "tool_query_quantities_contain"
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


def test_tool_query_quantities_ignore_optional_trailing_article_punctuation() -> None:
    turn = {
        "response": "",
        "function_results": [],
        "function_calls": [
            {
                "name": "search_products",
                "arguments": {
                    "queries": [{"query": "14.023пр", "requested_quantity": 2}]
                },
            }
        ],
    }

    assertion = eval_runner._assertion_result(
        {
            "type": "tool_query_quantities",
            "queries": [{"query": "14.023пр.", "requested_quantity": 2}],
        },
        turn,
        None,
    )

    assert assertion["passed"] is True


def test_tool_query_quantities_contain_accepts_extra_rechecks_and_product_alias() -> None:
    turn = {
        "response": "",
        "function_results": [],
        "function_calls": [
            {
                "name": "search_products",
                "arguments": {
                    "queries": [
                        {"query": "14.023л.", "requested_quantity": 2},
                        {"query": "22608", "requested_quantity": 4},
                    ]
                },
            }
        ],
    }

    assertion = eval_runner._assertion_result(
        {
            "type": "tool_query_quantities_contain",
            "queries": [
                {"query_any": ["P-AM02/B-S", "22608"], "requested_quantity": 4},
            ],
        },
        turn,
        None,
    )

    assert assertion["passed"] is True


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


def test_handoff_summary_assertion_accepts_semantic_alternatives() -> None:
    turn = {
        "response": "Передаю менеджеру.",
        "function_results": [],
        "function_calls": [
            {
                "name": "handoff_to_manager",
                "arguments": {
                    "reason": "order_creation",
                    "summary": "Заказ: одна P-AM02/B-S, самовывоз завтра, оплата наличными, Игорь, +7 900 444-55-66.",
                },
            }
        ],
    }

    assertion = eval_runner._assertion_result(
        {
            "type": "handoff_summary_contains_all",
            "values": [
                {"any": ["одна", "1 шт", "1 шту"]},
                "P-AM02/B-S",
                "самовывоз",
            ],
        },
        turn,
        "order_creation",
    )

    assert assertion["passed"] is True


def test_no_handoff_assertion_rejects_even_a_backend_rejected_tool_call() -> None:
    turn = {
        "response": "Проверьте итог.",
        "function_calls": [{"name": "handoff_to_manager", "arguments": {}}],
        "function_results": [
            {"name": "handoff_to_manager", "result": {"status": "rejected"}}
        ],
    }

    assertion = eval_runner._assertion_result({"type": "no_handoff"}, turn, None)

    assert assertion["passed"] is False


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


def legacy_stock_privacy_scans_exact_provider_messages() -> None:
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


def legacy_stock_privacy_scans_numeric_stock_json_fields() -> None:
    assertion = eval_runner._privacy_assertion(
        "Количество не раскрываю.",
        [],
        [{"name": "search_products", "result": {"stock": "31", "unit": "шт"}}],
    )

    assert assertion["passed"] is False
    assert "exact_stock:31" in assertion["detail"]


def test_stock_privacy_rejects_future_exact_stock_promises() -> None:
    rejected = eval_runner._privacy_assertion(
        "После уточнения кода скажу точный остаток.",
        [],
        [],
    )
    accepted = eval_runner._privacy_assertion(
        "Точный остаток не называю, проверю только нужное количество.",
        [],
        [],
    )

    assert rejected["passed"] is False
    assert "exact_stock_promise" in rejected["detail"]
    assert accepted["passed"] is True


def test_full_history_assertion_requires_exact_customer_turn_order() -> None:
    provider_requests = [
        {
            "messages": [
                {"role": "system", "content": "prompt"},
                {"role": "user", "content": "Второе сообщение"},
                {"role": "assistant", "content": "Ответ"},
                {"role": "user", "content": "Первое сообщение"},
            ]
        }
    ]

    assertion = eval_runner._full_history_assertion(
        provider_requests,
        ["Первое сообщение", "Второе сообщение"],
    )

    assert assertion["passed"] is False
    assert "customer_turns" in assertion["detail"]


def test_full_history_assertion_requires_balanced_chronological_tool_events() -> None:
    valid_messages = [
        {"role": "system", "content": "prompt"},
        {"role": "user", "content": "Проверьте 770"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "search_products", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "name": "search_products",
            "tool_call_id": "call-1",
            "content": "{}",
        },
        {"role": "assistant", "content": "Нашёл товар."},
        {"role": "user", "content": "Нужно две штуки"},
    ]
    valid = eval_runner._full_history_assertion(
        [{"messages": valid_messages}],
        ["Проверьте 770", "Нужно две штуки"],
    )
    missing_tool_result = eval_runner._full_history_assertion(
        [{"messages": valid_messages[:-3] + valid_messages[-2:]}],
        ["Проверьте 770", "Нужно две штуки"],
    )

    assert valid["passed"] is True
    assert missing_tool_result["passed"] is False
    assert "tool_history" in missing_tool_result["detail"]


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


def test_full_history_assertion_checks_every_provider_request() -> None:
    provider_requests = [
        {
            "messages": [
                {"role": "user", "content": "Хочу оформить заказ"},
                {"role": "assistant", "content": "Что вам нужно?"},
                {"role": "user", "content": "Две ручки"},
            ]
        },
        {"messages": [{"role": "user", "content": "Две ручки"}]},
    ]

    result = eval_runner._full_history_assertion(  # noqa: SLF001
        provider_requests,
        ["Хочу оформить заказ", "Две ручки"],
    )

    assert result["passed"] is False
    assert "request_2" in result["detail"]


def test_full_history_assertion_requires_previous_assistant_outputs() -> None:
    provider_requests = [
        {
            "messages": [
                {"role": "user", "content": "Хочу оформить заказ"},
                {"role": "user", "content": "Две ручки"},
            ]
        }
    ]

    result = eval_runner._full_history_assertion(  # noqa: SLF001
        provider_requests,
        ["Хочу оформить заказ", "Две ручки"],
        expected_assistant_outputs=["Что вам нужно?"],
    )

    assert result["passed"] is False
    assert "assistant_turns" in result["detail"]


def test_allowed_tools_assertion_checks_provider_results_and_declarations() -> None:
    provider_requests = [
        {
            "tools": [{"type": "web_search"}],
            "result": {
                "tool_calls": [
                    {"name": "web_search", "arguments": {"query": "AMIX"}, "call_id": "bad"}
                ]
            },
        }
    ]

    result = eval_runner._allowed_tools_assertion([], provider_requests)  # noqa: SLF001

    assert result["passed"] is False
    assert "web_search" in result["detail"]


def test_stock_privacy_checks_customer_output_but_allows_full_tool_history() -> None:
    safe = eval_runner._privacy_assertion(
        "Нужное количество доступно.",
        [],
        [{"name": "search_products", "result": {"stock": "31", "unit": "шт"}}],
        [{"messages": [{"role": "tool", "content": "{\"stock\":\"31\"}"}]}],
    )
    leaked = eval_runner._privacy_assertion(
        "Сейчас в наличии 31 шт.",
        [],
        [],
        [],
    )

    assert safe["passed"] is True
    assert leaked["passed"] is False
