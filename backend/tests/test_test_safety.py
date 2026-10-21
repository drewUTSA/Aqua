"""Red-side canaries for accidental credential inheritance and network escape."""

import socket

import psycopg
import pytest
from dotenv import load_dotenv
from safety import configure


def test_inherited_services_and_libpq_options_are_discarded():
    env = {
        "DATABASE_URL": "canary",
        "GEMINI_API_KEY": "canary",
        "INDEXER_DATABASE_URL": "canary",
        "PGSERVICE": "canary",
        "PGHOSTADDR": "canary",
        "AQUA_TEST_DATASET": "bank",
    }
    assert configure(env) == "postgresql://nl2sql_reader@127.0.0.1:5432/aqua_test_bank"
    assert "canary" not in env.values()
    assert env["PYTHON_DOTENV_DISABLED"] == "1"


def test_no_fixture_means_no_database():
    env = {"DATABASE_URL": "canary"}
    assert configure(env) == ""


@pytest.mark.parametrize("dataset", ["production", "bank?host=example.test", "../bank"])
def test_fixture_selector_cannot_supply_a_connection(dataset):
    with pytest.raises(RuntimeError):
        configure({"AQUA_TEST_DATASET": dataset})


def test_dotenv_cannot_reintroduce_service_configuration(tmp_path, monkeypatch):
    poison = tmp_path / ".env"
    poison.write_text("AQUA_DOTENV_CANARY=unexpected\n", encoding="utf-8")
    monkeypatch.delenv("AQUA_DOTENV_CANARY", raising=False)
    assert load_dotenv(poison) is False


def test_external_dns_is_refused():
    with pytest.raises(AssertionError, match="network access denied"):
        socket.getaddrinfo("example.test", 443)


def test_external_socket_is_refused():
    with (
        socket.socket() as sock,
        pytest.raises(AssertionError, match="network access denied"),
    ):
        sock.connect(("192.0.2.1", 443))


@pytest.mark.parametrize("connect", [psycopg.connect, psycopg.Connection.connect])
def test_libpq_cannot_bypass_the_socket_tripwire(connect):
    with pytest.raises(AssertionError, match="database access denied"):
        connect("postgresql://fixture@192.0.2.1/forbidden", connect_timeout=1)


def test_libpq_host_override_is_refused():
    with pytest.raises(AssertionError, match="database access denied"):
        psycopg.connect(
            "postgresql://nl2sql_reader@127.0.0.1:5432/aqua_test_bank",
            hostaddr="192.0.2.1",
        )
