"""No egress: inspect fixed origin, immutable body and provider idempotency."""

from contextlib import contextmanager
import uuid

import httpx
import pytest

from auth.mailconfig import MailUnavailable
from auth.mailtransport import ResendTransport
from auth.mailtemplates import TEMPLATE_VERSION, render


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
    assert set(calls[0][2]["json"]) == {"from", "to", "subject", "text"}
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


@pytest.mark.parametrize(
    "purpose", ["verify_email", "reset_password", "password_changed"]
)
def test_branded_delivery_keeps_durable_body_and_fixed_non_personal_tags(
    monkeypatch, purpose
):
    calls = []

    class Response:
        status_code = 200

        def iter_raw(self, **kwargs):
            yield b"{}"

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @contextmanager
        def stream(self, method, url, **kwargs):
            calls.append(kwargs)
            yield Response()

    monkeypatch.setattr(httpx, "Client", Client)
    payload = render(
        purpose,
        "fixture@example.invalid",
        None if purpose == "password_changed" else "M" * 43,
        "https://aqua-ai.us",
    )
    transport = ResendTransport("re_synthetic_fixture_key")
    job = uuid.uuid4()
    assert transport.send(job, payload) == "accepted"
    assert transport.send(job, payload) == "accepted"
    assert calls[0] == calls[1]
    assert calls[0]["json"]["html"] == payload["html"]
    assert calls[0]["json"]["text"] == payload["text"]
    assert calls[0]["json"]["tags"] == [
        {"name": "app", "value": "aqua"},
        {"name": "purpose", "value": purpose},
        {"name": "template", "value": TEMPLATE_VERSION},
    ]
    assert not {"origin", "purpose", "template_version"} & set(calls[0]["json"])


@pytest.mark.parametrize(
    "change", ["html", "purpose", "extra", "missing", "non_string"]
)
def test_branded_transport_rejects_divergent_content_before_any_provider_call(
    monkeypatch, change
):
    def no_transport(**kwargs):
        pytest.fail("invalid branded content reached the provider")

    monkeypatch.setattr(httpx, "Client", no_transport)
    payload = render(
        "verify_email", "fixture@example.invalid", "M" * 43, "https://aqua-ai.us"
    )
    if change == "html":
        payload["html"] += '<img src="https://tracking.invalid">'
    elif change == "purpose":
        payload["purpose"] = "arbitrary_personal_tag"
    elif change == "extra":
        payload["headers"] = "unsafe"
    elif change == "missing":
        del payload["text"]
    else:
        payload["html"] = None
    assert (
        ResendTransport("re_synthetic_fixture_key").send(uuid.uuid4(), payload)
        == "invalid"
    )
