from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import httpx


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from llm.openai_client import OpenAIService
from llm.prompts import SYSTEM_PROMPT
from settings import get_settings


KAIGO_ENDPOINT = "https://kaigo.space/codex-api/v1/respond"
KAIGO_MODELS = ("gpt-5.6-luna", "gpt-5.6-sol")
BENCHMARK_APPENDIX = """

РЕЖИМ СРАВНИТЕЛЬНОГО ТЕСТА
В этом запросе функции недоступны, а проверенные товарные факты уже переданы в сообщении.
Используй только эти факты и историю. Напиши только следующий ответ клиенту без служебных пояснений.
Если нужен менеджер, предложи подключить его, но не утверждай, что передача уже выполнена.
""".strip()


@dataclass(slots=True)
class BenchmarkCase:
    case_id: str
    title: str
    history: list[dict[str, str]]
    facts: str
    user_message: str
    required_all: list[str]
    required_any: list[list[str]] | None = None
    forbidden: list[str] | None = None


def benchmark_cases() -> list[BenchmarkCase]:
    return [
        BenchmarkCase(
            case_id="company_address",
            title="Живой вопрос об адресе",
            history=[
                {"role": "user", "content": "Добрый день, подскажите по наличию ручек."},
                {"role": "assistant", "content": "Добрый день! Напишите артикул или код, и я проверю."},
            ],
            facts="Адрес магазина AMIX: Санкт-Петербург, ул. Якорная, д. 15, лит. Б.",
            user_message="А где вы вообще находитесь?",
            required_all=["Санкт-Петербург", "Якорн", "15"],
            forbidden=["Москва"],
        ),
        BenchmarkCase(
            case_id="second_product_followup",
            title="Уточнение по второму товару",
            history=[
                {
                    "role": "user",
                    "content": "Нужно наличие узнать 14.023пр и P-AM02/B-S.",
                },
                {
                    "role": "assistant",
                    "content": "Проверил: обе позиции сейчас присутствуют в актуальной выгрузке.",
                },
            ],
            facts=(
                "Порядок товаров клиента: 1) 14.023пр.; 2) P-AM02/B-S. "
                "Обе позиции присутствуют. Точное требуемое количество для второй позиции клиент не назвал. "
                "Полный остаток раскрывать нельзя: нужно спросить, сколько штук требуется, и затем подтвердить да или нет."
            ),
            user_message="А по второму?",
            required_all=["P-AM02/B-S"],
            required_any=[["количеств", "сколько"]],
            forbidden=["220 шт", "1 шт"],
        ),
        BenchmarkCase(
            case_id="order_final_check",
            title="Финальная сверка заказа",
            history=[
                {"role": "user", "content": "Мне нужно оформить заказ."},
                {
                    "role": "assistant",
                    "content": "Хорошо. Напишите товары и количество, а дальше уточним получение и контакты.",
                },
                {"role": "user", "content": "Код 770 — 2 штуки и код 28834 — 3 штуки."},
                {
                    "role": "assistant",
                    "content": "Оба количества доступны. Как получить заказ, когда он нужен и как будете оплачивать?",
                },
                {
                    "role": "user",
                    "content": "Доставка в Тверь на следующей неделе, оплата наличными.",
                },
                {"role": "assistant", "content": "Тогда подскажите имя и телефон для связи."},
            ],
            facts=(
                "Код 770 — артикул 14.023пр., запрошено 2 штуки, количество доступно. "
                "Код 28834 — артикул МП ЦК белая, запрошено 3 штуки, количество доступно. "
                "Менеджер ещё не вызван. Перед передачей нужно показать полный итог и получить подтверждение клиента."
            ),
            user_message="Никита, +7 000 000-00-00.",
            required_all=[
                "770",
                "2",
                "28834",
                "3",
                "Твер",
                "наличными",
                "Никита",
                "+7 000 000-00-00",
            ],
            required_any=[
                ["верно", "правильно", "подтверд"],
                ["в наличии", "доступно", "доступны"],
            ],
            forbidden=["Передаю", "менеджер подключится", "вы заказали", "получатель"],
        ),
        BenchmarkCase(
            case_id="technical_difference",
            title="Техническое отличие без характеристик",
            history=[
                {"role": "user", "content": "14.023л и 14.023пр есть?"},
                {"role": "assistant", "content": "Обе позиции найдены."},
            ],
            facts=(
                "Для обеих позиций известны только код, артикул, цена, остаток, единица измерения и вес. "
                "Назначение, сторона установки, размеры, совместимость и другие технические характеристики отсутствуют."
            ),
            user_message="А чем они отличаются?",
            required_all=[],
            required_any=[
                [
                    "не могу",
                    "недостаточно",
                    "нет данных",
                    "не указаны",
                    "нет подробных",
                    "не получится",
                    "определить нельзя",
                    "характеристик нет",
                ],
                ["менеджер", "специалист"],
            ],
            forbidden=[
                "левый вариант",
                "правый вариант",
                "для левой",
                "для правой",
                "давайте я переключу",
                "только коды и цены",
            ],
        ),
    ]


def build_prompt(case: BenchmarkCase) -> str:
    history_json = json.dumps(case.history, ensure_ascii=False, indent=2)
    return (
        f"Сценарий: {case.title}\n\n"
        f"Хронологическая история диалога:\n{history_json}\n\n"
        f"Проверенные факты для этого ответа:\n{case.facts}\n\n"
        f"Последнее сообщение клиента:\n{case.user_message}"
    )


def evaluate_response(case: BenchmarkCase, text: str) -> dict[str, Any]:
    normalized = text.casefold()
    missing_required_all = [value for value in case.required_all if value.casefold() not in normalized]
    missing_required_any = [
        group
        for group in (case.required_any or [])
        if not any(value.casefold() in normalized for value in group)
    ]
    found_forbidden = [value for value in (case.forbidden or []) if value.casefold() in normalized]
    return {
        "passed": not missing_required_all and not missing_required_any and not found_forbidden,
        "missing_required_all": missing_required_all,
        "missing_required_any": missing_required_any,
        "found_forbidden": found_forbidden,
        "has_markdown": any(marker in text for marker in ("**", "```", "###")),
        "characters": len(text),
    }


def sanitize_result(result: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in result.items():
        if key.casefold() in {"api_key", "authorization", "token"}:
            continue
        if isinstance(value, dict):
            sanitized[key] = sanitize_result(value)
        elif isinstance(value, list):
            sanitized[key] = [sanitize_result(item) if isinstance(item, dict) else item for item in value]
        else:
            sanitized[key] = value
    return sanitized


def call_gemini(case: BenchmarkCase) -> dict[str, Any]:
    settings = get_settings()
    service = OpenAIService(settings)
    service.audit_logger.enabled = False
    started = time.monotonic()
    result = service.run_messages(
        messages=[
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{BENCHMARK_APPENDIX}"},
            {"role": "user", "content": build_prompt(case)},
        ],
        tools=None,
        tool_choice="none",
    )
    wall_ms = int((time.monotonic() - started) * 1000)
    return {
        "provider": "google_ai_studio",
        "model": service.google_ai_model,
        "reasoning_effort": service.google_ai_reasoning_effort,
        "status": "ok" if result.text else "error",
        "output_text": result.text or "",
        "error_type": result.error_type,
        "wall_ms": wall_ms,
        "provider_duration_ms": result.latency_ms,
        "usage": result.usage or {},
        "cost": result.cost or {},
    }


def call_kaigo(
    case: BenchmarkCase,
    *,
    model: str,
    reasoning_effort: str,
    api_key: str,
    endpoint: str = KAIGO_ENDPOINT,
    max_attempts: int = 3,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "reasoning_effort": reasoning_effort,
        "system_prompt": f"{SYSTEM_PROMPT}\n\n{BENCHMARK_APPENDIX}",
        "prompt": build_prompt(case),
    }
    started = time.monotonic()
    attempts: list[dict[str, Any]] = []
    response_payload: dict[str, Any] = {}
    status = "error"
    error_type: str | None = None

    with httpx.Client(timeout=httpx.Timeout(900.0, connect=20.0)) as client:
        for attempt in range(1, max_attempts + 1):
            response = client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            body: dict[str, Any]
            try:
                body = response.json()
            except ValueError:
                body = {"error": {"type": "invalid_json", "message": response.text[:500]}}
            attempts.append({"attempt": attempt, "http_status": response.status_code})
            if response.is_success:
                response_payload = body
                status = "ok"
                error_type = None
                break

            error = body.get("error") if isinstance(body, dict) else None
            error_type = error.get("type") if isinstance(error, dict) else f"http_{response.status_code}"
            response_payload = body
            retryable = response.status_code in {429, 502, 503, 504} or error_type in {
                "busy",
                "rate_limited",
                "provider_error",
                "codex_unavailable",
                "timeout",
            }
            if not retryable or attempt >= max_attempts:
                break
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else 7.0 * attempt
            time.sleep(min(delay, 30.0))

    wall_ms = int((time.monotonic() - started) * 1000)
    output_text = response_payload.get("output_text") if isinstance(response_payload, dict) else None
    return {
        "provider": "kaigo",
        "model": model,
        "reasoning_effort": reasoning_effort,
        "status": status,
        "output_text": output_text if isinstance(output_text, str) else "",
        "error_type": error_type,
        "wall_ms": wall_ms,
        "provider_duration_ms": response_payload.get("duration_ms") if isinstance(response_payload, dict) else None,
        "usage": response_payload.get("usage", {}) if isinstance(response_payload, dict) else {},
        "request_id": response_payload.get("request_id") if isinstance(response_payload, dict) else None,
        "attempts": attempts,
    }


def run_benchmark(*, kaigo_api_key: str, reasoning_effort: str) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    cases = benchmark_cases()
    results: list[dict[str, Any]] = []
    runners = [
        ("gemini", None),
        *[("kaigo", model) for model in KAIGO_MODELS],
    ]
    for provider, model in runners:
        for case in cases:
            if provider == "gemini":
                result = call_gemini(case)
            else:
                result = call_kaigo(
                    case,
                    model=str(model),
                    reasoning_effort=reasoning_effort,
                    api_key=kaigo_api_key,
                )
            result["case_id"] = case.case_id
            result["case_title"] = case.title
            result["evaluation"] = evaluate_response(case, result.get("output_text", ""))
            results.append(sanitize_result(result))
    return {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "method": {
            "reasoning_effort": reasoning_effort,
            "same_system_prompt": True,
            "same_case_prompts": True,
            "native_tools_used": False,
            "note": "Text-only quality comparison; production tool-call capability is assessed separately.",
        },
        "cases": [asdict(case) for case in cases],
        "results": results,
    }


def write_markdown_report(payload: dict[str, Any], path: Path) -> None:
    results = payload["results"]
    model_names = list(dict.fromkeys(result["model"] for result in results))
    lines = [
        "# Сравнение Gemini, Luna и Sol для AMIX",
        "",
        f"Начало: `{payload['started_at']}`",
        "",
        "Все модели получили одинаковый системный промпт, одинаковую историю и одинаковые синтетические факты. "
        "Нативные функции в этом прогоне отключены, поэтому таблица сравнивает именно качество следующего текстового ответа.",
        "",
        "## Сводка",
        "",
        "| Модель | Успешные ответы | Формальные условия | Среднее полное время | Среднее время провайдера | Входные токены | Выходные токены |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for model in model_names:
        model_results = [result for result in results if result["model"] == model]
        ok_count = sum(result["status"] == "ok" for result in model_results)
        passed_count = sum(bool(result["evaluation"]["passed"]) for result in model_results)
        average_ms = round(sum(int(result["wall_ms"]) for result in model_results) / max(len(model_results), 1))
        provider_durations = [
            int(result["provider_duration_ms"])
            for result in model_results
            if isinstance(result.get("provider_duration_ms"), (int, float))
        ]
        average_provider_ms = round(sum(provider_durations) / max(len(provider_durations), 1))
        input_tokens = sum(_usage_value(result["usage"], "input_tokens", "prompt_tokens") for result in model_results)
        output_tokens = sum(_usage_value(result["usage"], "output_tokens", "completion_tokens") for result in model_results)
        lines.append(
            f"| `{model}` | {ok_count}/{len(model_results)} | {passed_count}/{len(model_results)} | "
            f"{average_ms / 1000:.2f} с | {average_provider_ms / 1000:.2f} с | {input_tokens} | {output_tokens} |"
        )

    lines.extend(
        [
            "",
            "Формальные условия проверяют обязательные и запрещённые фразы, но не заменяют ручную оценку смысла. "
            "Полное время включает клиентское ограничение частоты запросов; чистое время провайдера находится в JSON.",
        ]
    )

    lines.extend(["", "## Ответы", ""])
    cases = {case["case_id"]: case for case in payload["cases"]}
    for case_id, case in cases.items():
        lines.extend([f"### {case['title']}", "", f"Клиент: {case['user_message']}", ""])
        for result in [item for item in results if item["case_id"] == case_id]:
            evaluation = result["evaluation"]
            lines.extend(
                [
                    f"**{result['model']}** — {result['wall_ms'] / 1000:.2f} с, "
                    f"проверка: {'пройдена' if evaluation['passed'] else 'не пройдена'}",
                    "",
                    result["output_text"] or f"Ошибка: {result.get('error_type')}",
                    "",
                ]
            )
            if not evaluation["passed"]:
                lines.append(
                    "Замечания автоматики: "
                    + json.dumps(
                        {
                            "missing_required_all": evaluation["missing_required_all"],
                            "missing_required_any": evaluation["missing_required_any"],
                            "found_forbidden": evaluation["found_forbidden"],
                        },
                        ensure_ascii=False,
                    )
                )
                lines.append("")

    lines.extend(
        [
            "## Ограничение сравнения",
            "",
            "Текущий Gemini-контур AMIX умеет нативно вызывать `search_products` и `handoff_to_manager`. "
            "Kaigo Codex Text API принимает только `system_prompt` и `prompt`, поэтому без отдельного оркестратора "
            "Luna и Sol не являются прямой заменой рабочего провайдера, даже если их текст лучше.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _usage_value(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare AMIX text answers across Gemini, Luna and Sol.")
    parser.add_argument("--output-dir", default="outputs/model-comparison")
    parser.add_argument("--reasoning-effort", default="low", choices=("low", "medium", "high", "xhigh", "max"))
    args = parser.parse_args()

    api_key = os.getenv("KAIGO_CODEX_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("KAIGO_CODEX_API_KEY is required.")

    payload = run_benchmark(kaigo_api_key=api_key, reasoning_effort=args.reasoning_effort)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "results.json"
    markdown_path = output_dir / "report.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_report(payload, markdown_path)
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
