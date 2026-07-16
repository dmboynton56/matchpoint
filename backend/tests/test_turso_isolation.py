import os

import pytest

import app.db.turso as turso


def test_pytest_session_uses_in_memory_turso():
    assert turso.TURSO_DATABASE_URL == ":memory:"
    assert os.getenv("MATCHPOINT_PYTEST_ISOLATE_TURSO") == "1"


def test_refuses_remote_turso_during_tests(monkeypatch):
    turso.close()
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://prod.example.turso.io")
    with pytest.raises(RuntimeError, match="Refusing to open remote Turso"):
        turso.get_client()
    turso.close()
    monkeypatch.setenv("TURSO_DATABASE_URL", ":memory:")
