import json

import httpx

from llm.openai_client import OpenAIService
from llm.prompts import build_product_facts_messages
from settings import get_settings


class DummyKieResponse:
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
            ]
        }


class DummyKieClient:
    def __init__(self, collector: dict) -> None:
        self.collector = collector

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, headers: dict, json: dict):
        self.collector["url"] = url
        self.collector["headers"] = headers
        self.collector["json"] = json
        return DummyKieResponse()


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
    assert collector["json"]["temperature"] == 0.6
    assert collector["json"]["top_p"] == 1.0
    assert collector["json"]["parallel_tool_calls"] is False
    assert "max_completion_tokens" not in collector["json"]
    assert collector["json"]["stream"] is False
    assert "stream_options" not in collector["json"]
    assert collector["json"]["messages"][0]["role"] == "system"
    assert collector["json"]["messages"][1]["role"] == "system"
    assert collector["json"]["messages"][2]["role"] == "user"


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
