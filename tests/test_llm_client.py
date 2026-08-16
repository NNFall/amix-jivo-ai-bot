import json
from pathlib import Path

import httpx

from llm.audit_log import LLMAuditLogger, LLMUsageStats, estimate_cost
from llm.openai_client import OpenAIService
from llm.prompts import SYSTEM_PROMPT
from llm.tool_schemas import OPENAI_TOOLS
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


class DummyKaigoResponse:
    def __init__(
        self,
        output_text: str,
        *,
        status_code: int = 200,
        response_json: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.output_text = output_text
        self.text = output_text
        self.response_json = response_json
        self.headers = headers or {}

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        if self.response_json is not None:
            return self.response_json
        return {
            "output_text": self.output_text,
            "usage": {
                "input_tokens": 900,
                "cached_input_tokens": 100,
                "output_tokens": 40,
            },
            "duration_ms": 1234,
            "request_id": "kaigo-test-request",
        }


class DummyKaigoClient:
    def __init__(self, collector: dict, responses: list[DummyKaigoResponse]) -> None:
        self.collector = collector
        self.responses = responses

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, headers: dict, json: dict, timeout=None):
        self.collector.setdefault("requests", []).append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        index = min(len(self.collector["requests"]) - 1, len(self.responses) - 1)
        return self.responses[index]


def _configure_kaigo(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "kaigo")
    monkeypatch.setenv("KAIGO_API_KEY", "test-kaigo-key")
    monkeypatch.setenv("KAIGO_API_URL", "https://kaigo.space/codex-api/v1/respond")
    monkeypatch.setenv("KAIGO_MODEL", "gpt-5.6-sol")
    monkeypatch.setenv("KAIGO_REASONING_EFFORT", "low")
    monkeypatch.setenv("KAIGO_RETRY_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("KAIGO_MIN_REQUEST_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()


def _configure_antigravity(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "antigravity")
    monkeypatch.setenv("ANTIGRAVITY_API_KEY", "test-antigravity-key")
    monkeypatch.setenv(
        "ANTIGRAVITY_API_URL",
        "https://kaigo.space/antigravity-api/v1/respond",
    )
    monkeypatch.setenv("ANTIGRAVITY_MODEL", "gemini-3.7-flash-low")
    monkeypatch.setenv("ANTIGRAVITY_REASONING_EFFORT", "low")
    monkeypatch.setenv("ANTIGRAVITY_NATIVE_TOOLS", "read_only")
    monkeypatch.setenv("ANTIGRAVITY_RETRY_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("ANTIGRAVITY_MIN_REQUEST_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()


def test_antigravity_payload_uses_native_client_tools_and_supported_history(
    monkeypatch,
    isolated_app_env,
) -> None:
    collector: dict = {}
    _configure_antigravity(monkeypatch)
    response = DummyKaigoResponse(
        "Такое количество доступно.",
        response_json={
            "output_text": "Такое количество доступно.",
            "tool_calls": [],
            "usage": {
                "input_tokens": 900,
                "output_tokens": 40,
                "thinking_tokens": 25,
                "total_tokens": 940,
            },
            "duration_ms": 1234,
        },
    )
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKaigoClient(collector, [response]))

    turn = OpenAIService(get_settings()).run_messages(
        messages=[
            {"role": "system", "content": "Главная инструкция AMIX"},
            {"role": "user", "content": "Проверьте код 770"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-old",
                        "type": "function",
                        "function": {
                            "name": "search_products",
                            "arguments": '{"queries":[{"query":"770"}]}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-old",
                "name": "search_products",
                "content": '{"status":"ok","requested_quantity_available":true}',
            },
            {"role": "user", "content": "Мне нужно 2 штуки"},
        ],
        tools=OPENAI_TOOLS,
        tool_choice="auto",
    )

    request = collector["requests"][0]
    assert request["url"] == "https://kaigo.space/antigravity-api/v1/respond"
    assert request["headers"]["Authorization"] == "Bearer test-antigravity-key"
    assert request["json"]["model"] == "gemini-3.7-flash-low"
    assert request["json"]["reasoning_effort"] == "low"
    assert request["json"]["system_prompt"] == "Главная инструкция AMIX"
    assert request["json"]["native_tools"] == "none"
    assert request["json"]["tool_choice"] == "auto"
    assert [tool["function"]["name"] for tool in request["json"]["tools"]] == [
        "search_products",
        "handoff_to_manager",
    ]
    assert [message["role"] for message in request["json"]["messages"]] == [
        "user",
        "tool",
        "user",
    ]
    assert request["json"]["messages"][1]["tool_call_id"] == "call-old"
    assert turn.text == "Такое количество доступно."
    assert turn.tool_calls == []
    assert turn.usage == {
        "prompt_tokens": 900,
        "completion_tokens": 15,
        "thinking_tokens": 25,
        "total_tokens": 940,
    }
    assert turn.latency_ms == 1234


def test_antigravity_parses_native_search_products_tool_call(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}
    _configure_antigravity(monkeypatch)
    response = DummyKaigoResponse(
        "",
        response_json={
            "output_text": None,
            "tool_calls": [
                {
                    "id": "call-antigravity-1",
                    "type": "function",
                    "function": {
                        "name": "search_products",
                        "arguments": {
                            "queries": [{"query": "770", "requested_quantity": 2}]
                        },
                    },
                }
            ],
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            "duration_ms": 500,
        },
    )
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKaigoClient(collector, [response]))

    turn = OpenAIService(get_settings()).run_messages(
        messages=[{"role": "user", "content": "Код 770, две штуки"}],
        tools=OPENAI_TOOLS,
    )

    assert turn.text is None
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].call_id == "call-antigravity-1"
    assert turn.tool_calls[0].name == "search_products"
    assert turn.tool_calls[0].arguments == {
        "queries": [{"query": "770", "requested_quantity": 2}]
    }


def test_antigravity_retries_busy_response(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}
    _configure_antigravity(monkeypatch)
    responses = [
        DummyKaigoResponse(
            "busy",
            status_code=429,
            response_json={"error": {"code": "busy", "message": "Server is busy"}},
            headers={"Retry-After": "0"},
        ),
        DummyKaigoResponse(
            "Проверил, всё доступно.",
            response_json={
                "output_text": "Проверил, всё доступно.",
                "tool_calls": [],
                "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
                "duration_ms": 300,
            },
        ),
    ]
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKaigoClient(collector, responses))

    turn = OpenAIService(get_settings()).run_messages(
        messages=[{"role": "user", "content": "Проверьте наличие"}],
        tools=OPENAI_TOOLS,
    )

    assert len(collector["requests"]) == 2
    assert turn.text == "Проверил, всё доступно."
    assert turn.error_type is None


def test_antigravity_retries_http_500_response(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}
    _configure_antigravity(monkeypatch)
    responses = [
        DummyKaigoResponse(
            "internal error",
            status_code=500,
            response_json={"error": {"code": "internal_error", "message": "Temporary failure"}},
            headers={"Retry-After": "0"},
        ),
        DummyKaigoResponse(
            "Повторный запрос выполнен.",
            response_json={
                "output_text": "Повторный запрос выполнен.",
                "tool_calls": [],
                "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
                "duration_ms": 300,
            },
        ),
    ]
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKaigoClient(collector, responses))

    turn = OpenAIService(get_settings()).run_messages(
        messages=[{"role": "user", "content": "Повторите запрос"}],
        tools=OPENAI_TOOLS,
    )

    assert len(collector["requests"]) == 2
    assert turn.text == "Повторный запрос выполнен."


def test_antigravity_parses_native_handoff_tool_call(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}
    _configure_antigravity(monkeypatch)
    response = DummyKaigoResponse(
        "",
        response_json={
            "output_text": None,
            "tool_calls": [
                {
                    "id": "call-antigravity-handoff",
                    "type": "function",
                    "function": {
                        "name": "handoff_to_manager",
                        "arguments": {
                            "reason": "client_requested_manager",
                            "summary": "Клиент просит менеджера.",
                            "customer_message": "Передаю вопрос менеджеру.",
                        },
                    },
                }
            ],
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            "duration_ms": 500,
        },
    )
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKaigoClient(collector, [response]))

    turn = OpenAIService(get_settings()).run_messages(
        messages=[{"role": "user", "content": "Позовите менеджера"}],
        tools=OPENAI_TOOLS,
    )

    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "handoff_to_manager"
    assert turn.tool_calls[0].arguments["reason"] == "client_requested_manager"


def test_kaigo_payload_serializes_full_history_and_tool_protocol(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}
    _configure_kaigo(monkeypatch)
    response = DummyKaigoResponse('{"type":"assistant","text":"Такое количество доступно."}')
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKaigoClient(collector, [response]))

    service = OpenAIService(get_settings())
    turn = service.run_messages(
        messages=[
            {"role": "system", "content": "Главная инструкция AMIX"},
            {"role": "user", "content": "Проверьте код 770"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-old",
                        "type": "function",
                        "function": {
                            "name": "search_products",
                            "arguments": '{"queries":[{"query":"770"}]}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-old",
                "name": "search_products",
                "content": '{"status":"ok","requested_quantity_available":true}',
            },
            {"role": "user", "content": "Мне нужно 2 штуки"},
        ],
        tools=OPENAI_TOOLS,
        tool_choice="auto",
    )

    request = collector["requests"][0]
    assert request["url"] == "https://kaigo.space/codex-api/v1/respond"
    assert request["headers"]["Authorization"] == "Bearer test-kaigo-key"
    assert request["json"]["model"] == "gpt-5.6-sol"
    assert request["json"]["reasoning_effort"] == "low"
    assert request["timeout"].read <= 300
    assert "Главная инструкция AMIX" in request["json"]["system_prompt"]
    assert "search_products" in request["json"]["system_prompt"]
    assert "handoff_to_manager" in request["json"]["system_prompt"]
    assert "Сначала примени правила основного системного промпта" in request["json"]["system_prompt"]
    assert "Не заменяй обязательную функцию уточняющим вопросом" in request["json"]["system_prompt"]
    assert "единственный допустимый ответ — tool_call search_products" in request["json"]["system_prompt"]
    assert "обязательный handoff всегда важнее поиска" in request["json"]["system_prompt"]
    assert '"role": "assistant"' in request["json"]["prompt"]
    assert '"role": "tool"' in request["json"]["prompt"]
    assert request["json"]["prompt"].index('"role": "assistant"') < request["json"]["prompt"].index('"role": "tool"')
    assert turn.text == "Такое количество доступно."
    assert turn.tool_calls == []
    assert turn.usage == {"prompt_tokens": 900, "completion_tokens": 40, "total_tokens": 940}
    assert turn.latency_ms == 1234


def test_kaigo_parses_search_products_tool_call(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}
    _configure_kaigo(monkeypatch)
    response = DummyKaigoResponse(
        '{"type":"tool_call","name":"search_products","arguments":'
        '{"queries":[{"query":"770","requested_quantity":2}]}}'
    )
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKaigoClient(collector, [response]))

    turn = OpenAIService(get_settings()).run_messages(
        messages=[{"role": "user", "content": "Код 770, две штуки"}],
        tools=OPENAI_TOOLS,
    )

    assert turn.text is None
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "search_products"
    assert turn.tool_calls[0].arguments == {
        "queries": [{"query": "770", "requested_quantity": 2}]
    }


def test_kaigo_parses_handoff_tool_call(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}
    _configure_kaigo(monkeypatch)
    response = DummyKaigoResponse(
        '{"type":"tool_call","name":"handoff_to_manager","arguments":'
        '{"reason":"client_requested_manager","summary":"Клиент просит менеджера.",'
        '"customer_message":"Передаю вопрос менеджеру."}}'
    )
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKaigoClient(collector, [response]))

    turn = OpenAIService(get_settings()).run_messages(
        messages=[{"role": "user", "content": "Позовите менеджера"}],
        tools=OPENAI_TOOLS,
    )

    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "handoff_to_manager"
    assert turn.tool_calls[0].arguments["reason"] == "client_requested_manager"


def test_kaigo_retries_invalid_protocol_once_and_accepts_correction(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}
    _configure_kaigo(monkeypatch)
    responses = [
        DummyKaigoResponse("Сейчас проверю товар."),
        DummyKaigoResponse(
            '{"type":"tool_call","name":"search_products",'
            '"arguments":{"queries":[{"query":"770"}]}}'
        ),
    ]
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKaigoClient(collector, responses))

    turn = OpenAIService(get_settings()).run_messages(
        messages=[{"role": "user", "content": "Проверьте 770"}],
        tools=OPENAI_TOOLS,
    )

    assert len(collector["requests"]) == 2
    assert "Предыдущий ответ нарушил обязательный JSON-формат" in collector["requests"][1]["json"]["prompt"]
    assert turn.tool_calls[0].name == "search_products"


def test_kaigo_never_executes_unknown_tool(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}
    _configure_kaigo(monkeypatch)
    response = DummyKaigoResponse(
        '{"type":"tool_call","name":"delete_products","arguments":{}}'
    )
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKaigoClient(collector, [response, response]))

    turn = OpenAIService(get_settings()).run_messages(
        messages=[{"role": "user", "content": "Удалите товар"}],
        tools=OPENAI_TOOLS,
    )

    assert len(collector["requests"]) == 2
    assert turn.tool_calls == []
    assert turn.text is None
    assert turn.error_type == "invalid_tool_protocol"


def test_kaigo_retries_rate_limit_and_returns_next_response(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}
    _configure_kaigo(monkeypatch)
    responses = [
        DummyKaigoResponse(
            "rate limited",
            status_code=429,
            response_json={
                "error": {
                    "type": "rate_limited",
                    "message": "Too many requests",
                }
            },
            headers={"Retry-After": "0"},
        ),
        DummyKaigoResponse('{"type":"assistant","text":"Проверил, всё доступно."}'),
    ]
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKaigoClient(collector, responses))

    turn = OpenAIService(get_settings()).run_messages(
        messages=[{"role": "user", "content": "Проверьте наличие"}],
        tools=OPENAI_TOOLS,
    )

    assert len(collector["requests"]) == 2
    assert turn.text == "Проверил, всё доступно."
    assert turn.error_type is None


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
    reply = service.run_messages(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Здравствуйте"},
            {"role": "user", "content": "Есть ли артикул AB-123?"},
        ]
    )

    assert reply.text == "Тестовый ответ от KIE"
    assert collector["url"] == "https://api.kie.ai/gpt-5-2/v1/chat/completions"
    assert collector["headers"]["Authorization"] == "Bearer test-kie-key"
    assert collector["json"]["reasoning_effort"] == "high"
    assert collector["json"]["temperature"] == 0.35
    assert collector["json"]["top_p"] == 1.0
    assert collector["json"]["parallel_tool_calls"] is False
    assert "max_completion_tokens" not in collector["json"]
    assert collector["json"]["stream"] is False
    assert "stream_options" not in collector["json"]
    assert [message["role"] for message in collector["json"]["messages"]] == [
        "system",
        "user",
        "user",
    ]


def test_kie_never_adds_web_search_to_amix_tools(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}

    monkeypatch.setenv("LLM_PROVIDER", "kie")
    monkeypatch.setenv("KIE_API_KEY", "test-kie-key")
    monkeypatch.setenv("KIE_ENABLE_WEB_SEARCH", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKieClient(collector))

    OpenAIService(get_settings()).run_messages(
        messages=[{"role": "user", "content": "Проверьте товар"}],
        tools=OPENAI_TOOLS,
        tool_choice="auto",
    )

    assert [tool["function"]["name"] for tool in collector["json"]["tools"]] == [
        "search_products",
        "handoff_to_manager",
    ]


def test_kie_never_adds_web_search_when_amix_turn_has_no_tools(monkeypatch, isolated_app_env) -> None:
    collector: dict = {}

    monkeypatch.setenv("LLM_PROVIDER", "kie")
    monkeypatch.setenv("KIE_API_KEY", "test-kie-key")
    monkeypatch.setenv("KIE_ENABLE_WEB_SEARCH", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyKieClient(collector))

    OpenAIService(get_settings()).run_messages(
        messages=[{"role": "user", "content": "Коротко переформулируй ответ"}],
        tools=None,
        tool_choice="none",
    )

    assert "tools" not in collector["json"]


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
                            "arguments": "{\"queries\":[{\"query\":\"14.023пр\"}]}",
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


def test_google_ai_studio_payload_keeps_tool_result_as_last_chronological_message(monkeypatch, isolated_app_env) -> None:
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
                        "id": "call_google_history_2",
                        "type": "function",
                        "function": {
                            "name": "search_products",
                            "arguments": "{\"queries\":[{\"query\":\"14.023пр\"}]}",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_google_history_2",
                "name": "search_products",
                "content": "{\"status\":\"ok\",\"stock\":\"220 шт\"}",
            },
        ],
        tools=None,
        tool_choice="none",
    )

    messages = collector["json"]["messages"]
    assert [message["role"] for message in messages] == ["system", "user", "assistant", "tool"]
    assert messages[3]["tool_call_id"] == "call_google_history_2"


def test_google_tool_call_thought_signature_survives_history_round_trip(isolated_app_env) -> None:
    service = OpenAIService(get_settings())
    signature = "encrypted-google-thought-signature"
    response = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "call_google_signature_1",
                            "type": "function",
                            "function": {
                                "name": "search_products",
                                "arguments": '{"queries":[{"query":"14.023pr"}]}',
                            },
                            "extra_content": {
                                "google": {
                                    "thought_signature": signature,
                                }
                            },
                        }
                    ]
                }
            }
        ]
    }

    calls = service._extract_kie_tool_calls(response)
    history_message = service.build_assistant_tool_call_message(calls)

    assert history_message["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": signature}
    }


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


def test_gemini_31_flash_lite_paid_pricing_includes_thinking_tokens() -> None:
    cost = estimate_cost(
        provider="google_ai_studio",
        model="gemini-3.1-flash-lite",
        usage=LLMUsageStats(
            prompt_tokens=1_000_000,
            completion_tokens=500_000,
            total_tokens=2_000_000,
        ),
        usd_to_rub=100,
    )

    assert cost.billable_input_tokens == 1_000_000
    assert cost.billable_output_tokens == 1_000_000
    assert cost.estimated_usd == 1.75
    assert cost.estimated_rub == 175


def test_sensitive_unbounded_debug_logs_are_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ASSISTANT_DEBUG_LOOKUP_LOGS", raising=False)
    monkeypatch.delenv("ASSISTANT_DEBUG_LLM_PAYLOADS", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.assistant_debug_lookup_logs is False
    assert settings.assistant_debug_llm_payloads is False


def test_model_has_only_product_search_and_manager_handoff_tools() -> None:
    assert [tool["function"]["name"] for tool in OPENAI_TOOLS] == [
        "search_products",
        "handoff_to_manager",
    ]


def test_product_search_tool_accepts_quantity_per_query() -> None:
    search_tool = next(tool for tool in OPENAI_TOOLS if tool["function"]["name"] == "search_products")
    properties = search_tool["function"]["parameters"]["properties"]
    query_schema = properties["queries"]["items"]

    assert query_schema["type"] == "object"
    assert query_schema["required"] == ["query"]
    assert "requested_quantity" in query_schema["properties"]
    assert "requested_quantity" not in properties


def legacy_prompt_requires_per_product_quantities_without_exact_stock_disclosure() -> None:
    assert "количество отдельно для каждой позиции" in SYSTEM_PROMPT
    assert "не раскрывай точный свободный остаток" in SYSTEM_PROMPT
    assert "только да/нет" in SYSTEM_PROMPT


def legacy_order_prompt_uses_history_instead_of_hidden_order_state() -> None:
    assert "полную хронологическую историю" in SYSTEM_PROMPT
    assert "Более позднее уточнение или исправление клиента заменяет ранее указанное значение" in SYSTEM_PROMPT
    assert "за один ответ задавай один естественный вопрос" in SYSTEM_PROMPT.lower()
    assert "показанный ему итог заказа" in SYSTEM_PROMPT
    assert "черновик заказа" not in SYSTEM_PROMPT.lower()


def legacy_order_prompt_does_not_search_or_handoff_before_there_is_enough_context() -> None:
    assert "Не вызывай поиск, пока искать ещё нечего" in SYSTEM_PROMPT
    assert "отсутствующие сведения заказа уточняй" in SYSTEM_PROMPT.lower()


def legacy_order_prompt_prioritizes_active_order_and_rechecks_changed_quantity() -> None:
    prompt = SYSTEM_PROMPT.lower()
    assert "активного заказа" in prompt
    assert "важнее общих правил" in prompt
    assert "количество изменилось" in prompt
    assert "проверь доступность заново" in prompt
    assert "не найден" in prompt
    assert "сохрани описание" in prompt


def legacy_prompt_rechecks_current_facts_after_customer_resolves_ambiguity() -> None:
    prompt = SYSTEM_PROMPT.lower()
    assert "уточнил конкретную позицию" in prompt
    assert "актуальные товарные факты" in prompt
    assert "вызови search_products" in prompt


def legacy_handoff_tool_does_not_treat_order_delivery_as_separate_handoff_reason() -> None:
    handoff_tool = next(
        tool for tool in OPENAI_TOOLS if tool["function"]["name"] == "handoff_to_manager"
    )
    description = handoff_tool["function"]["description"].lower()

    assert "сбор" in description
    assert "достав" in description
    assert "не" in description


def legacy_product_result_prompt_continues_confirmed_order_intake_from_history() -> None:
    prompt = PRODUCT_FACTS_RESPONSE_PROMPT.lower()
    assert "продолжи сбор заказа по истории" in prompt
    assert "один следующий недостающий вопрос" in prompt
    assert "до подтверждения итога" in prompt
    assert "сохрани описание" in prompt
    assert "не передавай менеджеру только из-за" in prompt
    assert "самостоятельный вопрос о наличии" in prompt
    assert "вызови search_products" not in prompt


def test_provider_audit_redacts_order_contact_and_invoice_data(tmp_path: Path) -> None:
    path = tmp_path / "audit.json"
    logger = LLMAuditLogger(enabled=True, path=str(path), max_entries=10, usd_to_rub=100)

    logger.write(
        {
            "request": {
                "json": {
                    "contact": {"name": "Ирина", "phone": "+7 900 111-22-33", "email": "irina@example.ru"},
                    "payment": {"company_name": "ООО Мебель", "inn": "1234567890", "kpp": "123456789"},
                    "message": "Позвоните +7 900 111-22-33, счёт на irina@example.ru, ИНН 1234567890",
                }
            }
        }
    )

    content = path.read_text(encoding="utf-8")
    assert "+7 900 111-22-33" not in content
    assert "irina@example.ru" not in content
    assert "1234567890" not in content
    assert "ООО Мебель" not in content
    assert "<redacted-phone>" in content
    assert "<redacted-email>" in content
    assert "<redacted-inn>" in content


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
