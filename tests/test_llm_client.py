import httpx

from llm.openai_client import OpenAIService
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
    assert collector["json"]["messages"][0]["role"] == "system"
    assert collector["json"]["messages"][1]["role"] == "user"
