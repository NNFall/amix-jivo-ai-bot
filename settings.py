from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE_PATH = BASE_DIR / "data" / "amix_jivo.db"


class Settings(BaseSettings):
    app_name: str = "amix-jivo"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    admin_username: str = "admin"
    admin_password: str = "change-me"
    products_xml_remote_url: str = "https://amix-tk.ru/files/1C/prices.xml"
    products_xml_auto_import_enabled: bool = False
    products_xml_auto_import_interval_seconds: int = 1800
    products_xml_auto_import_run_on_startup: bool = True
    products_xml_download_timeout_seconds: int = 60

    database_url: str = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
    history_limit: int = 20
    turn_debounce_seconds: float = 1.2

    jivo_webhook_token: str = "change-me"
    jivo_bot_api_url: str = ""
    jivo_api_timeout_seconds: int = 10

    llm_provider: str = "openai"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    kie_api_key: str | None = None
    kie_api_base_url: str = "https://api.kie.ai"
    kie_chat_model_path: str = "/gemini-3-pro/v1/chat/completions"
    kie_reasoning_effort: str = "low"
    kie_temperature: float = 0.35
    kie_top_p: float = 1.0
    kie_parallel_tool_calls: bool = False
    kie_stream: bool = False
    kie_http_connect_timeout_seconds: int = 10
    kie_http_read_timeout_seconds: int = 180
    kie_retry_max_attempts: int = 4
    kie_retry_total_timeout_seconds: int = 120
    kie_enable_web_search: bool = False
    google_ai_api_key: str | None = None
    google_ai_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    google_ai_model: str = "gemini-3.1-flash-lite"
    google_ai_reasoning_effort: str = "low"
    google_ai_temperature: float = 0.35
    google_ai_top_p: float = 1.0
    google_ai_stream: bool = False
    google_ai_http_connect_timeout_seconds: int = 10
    google_ai_http_read_timeout_seconds: int = 180
    google_ai_retry_max_attempts: int = 4
    google_ai_retry_total_timeout_seconds: int = 120
    google_ai_min_request_interval_seconds: float = 13.0
    google_ai_rate_limit_retry_delay_seconds: float = 65.0
    assistant_debug_lookup_logs: bool = False
    assistant_debug_llm_payloads: bool = False
    assistant_debug_llm_payloads_path: str = "data/logs/llm_debug.jsonl"
    llm_audit_log_enabled: bool = True
    llm_audit_log_path: str = "data/logs/llm_audit_recent.json"
    llm_audit_log_max_entries: int = 100
    llm_cost_usd_to_rub: float = 100.0
    show_corporate_price: bool = True

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_demo_poll_timeout_seconds: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
