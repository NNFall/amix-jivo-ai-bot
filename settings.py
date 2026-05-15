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

    database_url: str = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
    history_limit: int = 20

    jivo_webhook_token: str = "change-me"
    jivo_bot_api_url: str = ""
    jivo_api_timeout_seconds: int = 10

    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"

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
