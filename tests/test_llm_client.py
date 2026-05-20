import json
from pathlib import Path

import httpx

from llm.openai_client import OpenAIService
from llm.prompts import build_product_facts_messages
from settings import get_settings


class DummyKieResponse:
    status_code = 200
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": "Тестовый ответ от KIE",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "total_tokens": 1100,
            },
        }


class DummyKieLimitResponse:
    status_code = 200
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": "You've hit your limit. Please try again later.",
                    }
                }
            ]
        }


class DummyKieFailureResponse:
    status_code = 200
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "status": "failure",
            "error_code": 500,
            "error_message": "Server exception, please try again later",
        }


class DummyKieClient:
    def __init__(self, collector: dict, response=None) -> None:
        self.collector = collector
        self.response = response or DummyKieResponse()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, headers: dict, json: dict):
        self.collector["url"] = url
        self.collector["headers"] = headers
        self.collector["json"] = json
        self.collector["calls"] = self.collector.get("calls", 0) + 1
        if isinstance(self.response, list):
            index = min(self.collector["calls"] - 1, len(self.response) - 1)
            return self.response[index]
        return self.response


def test_openai_service_uses_kie_provider(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}

    monkeypatch.setenv("LLM_PROVIDER", "kie")
    monkeypatch.setenv("KIE_API_KEY", "test-kie-key")
    monkeypatch.setenv("KIE_API_BASE_URL", "https://api.kie.ai")
    monkeypatch.setenv("KIE_CHAT_MODEL_PATH", "/gpt-5-2/v1/chat/completions")
    monkeypatch.setenv("KIE_REASONING_EFFORT", "high")
    get_settings.cache_clear()

    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKieClient(collector))

    service = OpenAIService(get_settings())
    reply = service.generate_reply("Есть ли артикул AB-123?", "Клиент: Здравствуйте")

    assert reply == "Тестовый ответ от KIE"
    assert collector["url"] == "https://api.kie.ai/gpt-5-2/v1/chat/completions"
    assert collector["headers"]["Authorization"] == "Bearer test-kie-key"
    assert collector["json"]["reasoning_effort"] == "high"
    assert collector["json"]["temperature"] == 0.35
    assert collector["json"]["top_p"] == 1.0
    assert collector["json"]["parallel_tool_calls"] is False
    assert "max_completion_tokens" not in collector["json"]
    assert collector["json"]["stream"] is False
    assert "stream_options" not in collector["json"]
    assert collector["json"]["messages"][0]["role"] == "system"
    assert collector["json"]["messages"][1]["role"] == "system"
    assert collector["json"]["messages"][2]["role"] == "user"


def test_openai_service_uses_google_ai_studio_provider(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}

    monkeypatch.setenv("LLM_PROVIDER", "google_ai_studio")
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "test-google-key")
    monkeypatch.setenv("GOOGLE_AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
    monkeypatch.setenv("GOOGLE_AI_MODEL", "gemini-3-flash-preview")
    monkeypatch.setenv("GOOGLE_AI_REASONING_EFFORT", "low")
    get_settings.cache_clear()

    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKieClient(collector))

    service = OpenAIService(get_settings())
    turn = service.run_messages(
        messages=[
            {"role": "system", "content": "system prompt"},
            {"role": "system", "content": "TOOL_RESULTS_JSON:\n{}"},
            {"role": "user", "content": "test"},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "search_products",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        tool_choice="auto",
    )

    assert turn.text and "KIE" in turn.text
    assert collector["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert collector["headers"]["Authorization"] == "Bearer test-google-key"
    assert collector["json"]["model"] == "gemini-3-flash-preview"
    assert collector["json"]["reasoning_effort"] == "low"
    assert collector["json"]["temperature"] == 0.35
    assert collector["json"]["top_p"] == 1.0
    assert collector["json"]["stream"] is False
    assert collector["json"]["tool_choice"] == "auto"
    assert collector["json"]["tools"][0]["function"]["name"] == "search_products"
    assert [message["role"] for message in collector["json"]["messages"]] == ["system", "user"]
    assert "system prompt" in collector["json"]["messages"][0]["content"]
    assert "TOOL_RESULTS_JSON" in collector["json"]["messages"][0]["content"]
    assert "parallel_tool_calls" not in collector["json"]
    assert "max_completion_tokens" not in collector["json"]
    assert "stream_options" not in collector["json"]


def test_google_ai_studio_payload_preserves_tool_role_history(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}

    monkeypatch.setenv("LLM_PROVIDER", "google_ai_studio")
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "test-google-key")
    get_settings.cache_clear()

    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKieClient(collector))

    service = OpenAIService(get_settings())
    service.run_messages(
        messages=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "check product"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_google_history_1",
                        "type": "function",
                        "function": {
                            "name": "search_products",
                            "arguments": "{\"queries\":[\"14.023пр\"],\"intent\":\"stock\"}",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_google_history_1",
                "name": "search_products",
                "content": "{\"status\":\"ok\",\"stock\":\"220 шт\"}",
            },
            {"role": "user", "content": "answer"},
        ],
        tools=None,
        tool_choice="none",
    )

    messages = collector["json"]["messages"]
    assert [message["role"] for message in messages] == ["system", "user", "assistant", "tool", "user"]
    assert messages[2]["tool_calls"][0]["function"]["name"] == "search_products"
    assert messages[3]["tool_call_id"] == "call_google_history_1"


def test_google_ai_studio_audit_log_records_payload_usage_and_cost(monkeypatch, isolated_app_env, tmp_path) -> None:
    collector: dict = {}
    audit_path = tmp_path / "llm_audit_recent.json"

    monkeypatch.setenv("LLM_PROVIDER", "google_ai_studio")
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "test-google-key")
    monkeypatch.setenv("GOOGLE_AI_MODEL", "gemini-3-flash-preview")
    monkeypatch.setenv("LLM_AUDIT_LOG_ENABLED", "true")
    monkeypatch.setenv("LLM_AUDIT_LOG_PATH", str(audit_path))
    monkeypatch.setenv("LLM_AUDIT_LOG_MAX_ENTRIES", "2")
    monkeypatch.setenv("LLM_COST_USD_TO_RUB", "100")
    get_settings.cache_clear()

    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKieClient(collector))

    service = OpenAIService(get_settings())
    turn = service.run_messages(messages=[{"role": "user", "content": "Reply OK"}])

    assert turn.usage == {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100}
    assert turn.cost and turn.cost["estimated_usd"] == 0.0008
    assert turn.cost["billable_output_tokens"] == 100
    assert audit_path.exists()
    data = json.loads(Path(audit_path).read_text(encoding="utf-8"))
    entry = data["entries"][-1]
    assert entry["provider"] == "google_ai_studio"
    assert entry["duration_ms"] >= 0
    assert entry["request"]["headers"]["Authorization"] == "<redacted>"
    assert entry["request"]["json"]["model"] == "gemini-3-flash-preview"
    assert entry["response"]["usage"]["total_tokens"] == 1100
    assert entry["cost"]["estimated_rub"] == 0.08


def test_provider_request_throttle_waits_between_google_calls(monkeypatch) -> None:
    OpenAIService._provider_last_request_at.clear()
    sleeps: list[float] = []
    now = {"value": 100.0}

    def fake_monotonic() -> float:
        return now["value"]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now["value"] += seconds

    monkeypatch.setattr("llm.openai_client.time.monotonic", fake_monotonic)
    monkeypatch.setattr("llm.openai_client.time.sleep", fake_sleep)

    OpenAIService._throttle_provider_request(provider_key="google:test", min_interval_seconds=13.0)
    now["value"] += 3.0
    OpenAIService._throttle_provider_request(provider_key="google:test", min_interval_seconds=13.0)

    assert sleeps == [10.0]


def test_rate_limit_retry_uses_long_delay(monkeypatch) -> None:
    sleeps: list[float] = []

    monkeypatch.setattr("llm.openai_client.random.uniform", lambda start, end: 1.0)
    monkeypatch.setattr("llm.openai_client.time.sleep", lambda seconds: sleeps.append(seconds))

    OpenAIService._sleep_before_provider_retry(
        attempt=1,
        error_type="rate_limit_or_quota",
        rate_limit_retry_delay_seconds=65.0,
    )

    assert sleeps == [66.0]


def test_product_facts_messages_include_grouped_result_and_backend_actions() -> None:
    messages = build_product_facts_messages(
        transcript="Клиент: тест",
        customer_text="Сравните 14.023л. и 14.023пр.",
        product_lookup_result={
            "queries": ["14.023л.", "14.023пр."],
            "results": [
                {"query": "14.023л.", "status": "exact_found", "exact_matches": [{"code": "769"}]},
                {"query": "14.023пр.", "status": "exact_found", "exact_matches": [{"code": "770"}]},
            ],
            "summary": {"total_queries": 2, "total_exact_matches": 2},
        },
        backend_actions={
            "search_products_called": True,
            "handoff_to_manager_called": True,
            "handoff_reason": "complex_technical_question",
        },
    )

    context_content = messages[1]["content"]
    tool_content = next(message["content"] for message in messages if str(message.get("content", "")).startswith("TOOL_RESULTS_JSON"))
    internal_context = json.loads(context_content.removeprefix("INTERNAL_CONTEXT_JSON:\n"))

    assert messages[-1]["content"].startswith("TOOL_RESULTS_JSON")
    assert messages[-2]["role"] == "user"
    assert messages[-2]["content"] == "Сравните 14.023л. и 14.023пр."
    assert "INTERNAL_CONTEXT_JSON" in context_content
    assert "backend_actions" in context_content
    assert "handoff_to_manager_called" in context_content
    assert "last_product_lookup" not in internal_context
    assert "TOOL_RESULTS_JSON" in tool_content
    assert "backend_prelookup" in tool_content
    assert "results" in tool_content
    assert "14.023л." in tool_content


def test_kie_payload_preserves_tool_role_messages(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}

    monkeypatch.setenv("LLM_PROVIDER", "kie")
    monkeypatch.setenv("KIE_API_KEY", "test-kie-key")
    get_settings.cache_clear()
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKieClient(collector))

    service = OpenAIService(get_settings())
    service.run_messages(
        messages=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "сколько стоит 14.025пр."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "search_products", "arguments": '{"queries":["14.025пр."]}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "search_products",
                "content": '{"status":"ok"}',
            },
        ]
    )

    payload_messages = collector["json"]["messages"]
    assert payload_messages[0]["content"] == "system prompt"
    assert payload_messages[1]["content"] == "сколько стоит 14.025пр."
    assert payload_messages[2]["role"] == "assistant"
    assert payload_messages[2]["tool_calls"][0]["id"] == "call_1"
    assert payload_messages[3]["role"] == "tool"
    assert payload_messages[3]["tool_call_id"] == "call_1"
    assert payload_messages[3]["name"] == "search_products"
    assert payload_messages[3]["content"] == '{"status":"ok"}'


def test_kie_limit_text_is_provider_error(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}

    monkeypatch.setenv("LLM_PROVIDER", "kie")
    monkeypatch.setenv("KIE_API_KEY", "test-kie-key")
    monkeypatch.setenv("KIE_RETRY_MAX_ATTEMPTS", "1")
    get_settings.cache_clear()
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKieClient(collector, response=DummyKieLimitResponse()))

    service = OpenAIService(get_settings())
    turn = service.run_messages(messages=[{"role": "user", "content": "скидки есть?"}])

    assert turn.text is None
    assert turn.error_type == "rate_limit_or_quota"
    assert turn.retryable is True


def test_kie_failure_body_is_retried(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}

    monkeypatch.setenv("LLM_PROVIDER", "kie")
    monkeypatch.setenv("KIE_API_KEY", "test-kie-key")
    monkeypatch.setenv("KIE_RETRY_MAX_ATTEMPTS", "2")
    get_settings.cache_clear()
    monkeypatch.setattr(OpenAIService, "_sleep_before_retry", staticmethod(lambda attempt: None))
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda timeout: DummyKieClient(collector, response=[DummyKieFailureResponse(), DummyKieResponse()]),
    )

    service = OpenAIService(get_settings())
    turn = service.run_messages(messages=[{"role": "user", "content": "а есть мп дешевле?"}])

    assert collector["calls"] == 2
    assert turn.text == "Тестовый ответ от KIE"
    assert turn.error_type is None
