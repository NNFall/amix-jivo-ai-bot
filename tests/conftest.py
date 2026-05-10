from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database.db as db_module
from database.models import Base
from settings import get_settings


@pytest.fixture
def isolated_app_env(monkeypatch, tmp_path) -> Iterator[None]:
    database_path = tmp_path / "test.db"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("JIVO_WEBHOOK_TOKEN", "test-token")
    monkeypatch.setenv("JIVO_BOT_API_URL", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()

    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_local)

    Base.metadata.create_all(bind=engine)
    yield
    get_settings.cache_clear()
