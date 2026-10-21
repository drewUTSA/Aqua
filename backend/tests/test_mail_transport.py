"""No egress: inspect fixed origin, immutable body and provider idempotency."""

from contextlib import contextmanager
import uuid

import httpx
import pytest

from auth.mailconfig import MailUnavailable
from auth.mailtransport import ResendTransport


@pytest.mark.parametrize(
    "status,outcome",
    [
        (200, "accepted"),
        (201, "accepted"),
        (400, "permanent"),
        (401, "permanent"),
        (302, "permanent"),
        (409, "permanent"),
        (429, "retry"),
        (500, "retry"),
    ],
)
def test_transport_owns_no_retries_and_never_redirects(monkeypatch, status, outcome):
    calls = []

    class Response:
        status_code = status

        def iter_raw(self, **kwargs):
            yield b'{"id":"synthetic-id"}'

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @contextmanager
        def stream(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            yield Response()

    monkeypatch.setattr(httpx, "Client", Client)
    transport = ResendTransport("re_synthetic_fixture_key")
    job_id = uuid.uuid4()
    payload = {
        "to": "fixture@example.invalid",
        "subject": "Synthetic test",
        "text": "synthetic body",
    }
    assert transport.send(job_id, payload) == outcome
    assert len(calls) == 1
    assert calls[0][:2] == ("POST", "https://api.resend.com/emails")
    assert calls[0][2]["headers"]["Idempotency-Key"] == "aqua-account-mail/" + str(
        job_id
    )
    assert calls[0][2]["json"]["text"] == "synthetic body"
    assert "re_synthetic_fixture_key" not in repr(transport)


def test_unknown_network_acceptance_is_bounded_retry_category(monkeypatch):
    class Unavailable:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            raise httpx.ReadTimeout("PRIVATE_ERROR_TOKEN_CANARY")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(httpx, "Client", Unavailable)
    assert (
        ResendTransport("re_synthetic_fixture_key").send(
            uuid.uuid4(),
            {"to": "fixture@example.invalid", "subject": "test", "text": "test"},
        )
        == "retry"
    )


def test_large_provider_response_does_not_buffer_unlimited_data(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        def iter_raw(self, **kwargs):
            for _ in range(8):
                calls.append(1)
                yield b"x" * 4096

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @contextmanager
        def stream(self, *args, **kwargs):
            yield Response()

    monkeypatch.setattr(httpx, "Client", Client)
    assert (
        ResendTransport("re_synthetic_fixture_key").send(
            uuid.uuid4(),
            {"to": "fixture@example.invalid", "subject": "test", "text": "test"},
        )
        == "retry"
    )
    assert len(calls) == 5


@pytest.mark.parametrize(
    "key", ["", "not-resend", "re_bad\nHeader: injected", "re_short"]
)
def test_worker_rejects_missing_and_header_injected_provider_key(key):
    with pytest.raises(MailUnavailable):
        ResendTransport(key)
