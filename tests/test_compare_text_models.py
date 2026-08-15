from __future__ import annotations

from scripts.compare_text_models import (
    BenchmarkCase,
    build_prompt,
    evaluate_response,
    sanitize_result,
    write_markdown_report,
)


def test_build_prompt_keeps_history_facts_and_latest_message() -> None:
    case = BenchmarkCase(
        case_id="followup",
        title="Уточнение по второму товару",
        history=[
            {"role": "user", "content": "Проверьте А и Б"},
            {"role": "assistant", "content": "Оба товара найдены."},
        ],
        facts="А: доступно. Б: доступно.",
        user_message="А по второму?",
        required_all=["Б"],
        forbidden=["точный остаток"],
    )

    prompt = build_prompt(case)

    assert "Проверьте А и Б" in prompt
    assert "Оба товара найдены." in prompt
    assert "А: доступно. Б: доступно." in prompt
    assert prompt.rstrip().endswith("А по второму?")


def test_evaluate_response_reports_missing_and_forbidden_phrases() -> None:
    case = BenchmarkCase(
        case_id="technical",
        title="Технический вопрос",
        history=[],
        facts="Технических характеристик нет.",
        user_message="Чем отличаются?",
        required_all=["не могу"],
        required_any=[["менеджер", "специалист"]],
        forbidden=["левый"],
    )

    evaluation = evaluate_response(case, "Это левый вариант.")

    assert evaluation["passed"] is False
    assert evaluation["missing_required_all"] == ["не могу"]
    assert evaluation["missing_required_any"] == [["менеджер", "специалист"]]
    assert evaluation["found_forbidden"] == ["левый"]


def test_sanitize_result_does_not_serialize_api_key() -> None:
    result = {
        "provider": "kaigo",
        "api_key": "secret-value",
        "request": {"model": "gpt-5.6-luna", "prompt": "test"},
        "response": {"output_text": "ok"},
    }

    sanitized = sanitize_result(result)

    assert "api_key" not in sanitized
    assert "secret-value" not in str(sanitized)
    assert sanitized["request"]["model"] == "gpt-5.6-luna"


def test_markdown_report_separates_wall_and_provider_time(tmp_path) -> None:
    payload = {
        "started_at": "2026-08-15T00:00:00+00:00",
        "cases": [],
        "results": [
            {
                "model": "example-model",
                "status": "ok",
                "wall_ms": 6000,
                "provider_duration_ms": 4000,
                "usage": {"input_tokens": 10, "output_tokens": 2},
                "evaluation": {"passed": True},
                "case_id": "unused",
            }
        ],
    }
    report_path = tmp_path / "report.md"

    write_markdown_report(payload, report_path)

    report = report_path.read_text(encoding="utf-8")
    assert "Среднее полное время" in report
    assert "Среднее время провайдера" in report
    assert "6.00 с" in report
    assert "4.00 с" in report
