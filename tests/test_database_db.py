import sqlite3

import database.db as db_module


def test_sqlite_connect_args_include_busy_timeout() -> None:
    args = db_module._sqlite_connect_args("sqlite:///tmp/test.db")

    assert args["check_same_thread"] is False
    assert args["timeout"] >= 30


def test_sqlite_connection_is_configured_for_concurrent_reads_and_writes(tmp_path) -> None:
    database_path = tmp_path / "wal-test.db"
    connection = sqlite3.connect(database_path)

    db_module._configure_sqlite_connection(connection, None)

    journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert journal_mode.lower() == "wal"
    assert busy_timeout >= 30000
