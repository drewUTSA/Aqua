"""Offline tests and explicitly selected disposable PostgreSQL fixtures."""

# Settings are loaded during collection. Install before any application import.
from safety import install

install()

import pytest  # noqa: E402 - safety guard must precede application imports

pytest_plugins = ("workspace_fixtures",)

from nl2sql.config import load_settings  # noqa: E402
from nl2sql.db import connect  # noqa: E402


@pytest.fixture(scope="session")
def live_database() -> str:
    """'bank' or 'pagila'. Skips without an explicit synthetic dataset.

    An unreachable database is an error, not a skip, so an outage is
    never mistaken for a pass.
    """
    settings = load_settings()
    if not settings.database_url:
        pytest.skip("disposable database not selected; use tools/checks/run_backend.py")
    with connect(settings) as conn:
        bank, pagila = conn.execute(
            "SELECT to_regclass('public.trans') IS NOT NULL,"
            " to_regclass('public.film') IS NOT NULL"
        ).fetchone()
    if bank:
        return "bank"
    if pagila:
        return "pagila"
    pytest.fail("synthetic fixture has neither bank nor Pagila tables")


@pytest.fixture
def on_bank(live_database: str) -> None:
    if live_database != "bank":
        pytest.skip("needs the bank service; DATABASE_URL points at Pagila")


@pytest.fixture
def on_pagila(live_database: str) -> None:
    if live_database != "pagila":
        pytest.skip("needs the Pagila service; DATABASE_URL points at the bank")


@pytest.fixture(autouse=True)
def no_answer_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """API tests ask the same placeholder question many times with
    different stand-in pipelines; a cached answer would leak between
    them. Tests of the cache itself install their own."""
    try:
        import main
    except ImportError:
        return
    from nl2sql.cache import AnswerCache

    monkeypatch.setattr(main, "ANSWER_CACHE", AnswerCache(0))


@pytest.fixture(autouse=True)
def no_real_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests must never spend API quota (CLAUDE.md). Any code path
    that builds a real Gemini client, for example a fallback step a test
    forgot to stub, fails loudly instead of calling Google."""
    from google import genai

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to create a real Gemini client")

    monkeypatch.setattr(genai, "Client", refuse)


# Fixture imports register the explicitly isolated private app database.
from storage_fixtures import app_database, storage  # noqa: E402,F401
