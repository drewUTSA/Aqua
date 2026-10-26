"""Synthetic branded messages keep links, content and provider tags canonical."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import hashlib
import json
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

from auth.mailconfig import MailPolicy, MailUnavailable
from auth.mailoutbox import MailJob, _aad, open_job
from auth.mailtemplates import NOTICE, TEMPLATE_VERSION, render, validate

ORIGIN = "https://aqua-ai.us"
TOKEN = "M" * 43
RECIPIENT = "fixture@example.invalid"
POLICY = MailPolicy(True, b"K" * 32)
PURPOSES = ("verify_email", "reset_password", "password_changed")


class Content(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.links = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        for name, value in attrs:
            assert not name.lower().startswith("on")
            assert name not in {"src", "srcset", "action", "background"}
            if name == "style":
                assert "url(" not in value.lower()
            if name == "href":
                self.links.append(value)


@pytest.mark.parametrize("purpose", PURPOSES)
def test_branded_html_has_only_the_canonical_cta_and_plain_fallback(purpose):
    token = None if purpose == "password_changed" else TOKEN
    payload = render(purpose, RECIPIENT, token, ORIGIN)
    validate(purpose, payload, ORIGIN)
    assert payload["template_version"] == TEMPLATE_VERSION
    assert payload["purpose"] == purpose and payload["origin"] == ORIGIN
    assert "AQUA" in payload["html"] and "AQUA" in payload["subject"]
    parsed = Content()
    parsed.feed(payload["html"])
    assert not {"script", "iframe", "form", "img", "svg", "link", "object"} & set(
        parsed.tags
    )
    if purpose == "password_changed":
        assert parsed.links == [ORIGIN + "/forgot-password"]
        assert ORIGIN + "/forgot-password" in payload["text"]
        assert TOKEN not in payload["text"] + payload["html"]
    else:
        path = "/verify-email" if purpose == "verify_email" else "/reset-password"
        expected = ORIGIN + path + "#token=" + TOKEN
        assert parsed.links == [expected]
        assert expected in payload["text"]


@pytest.mark.parametrize("purpose", PURPOSES)
def test_branded_envelope_stays_within_existing_four_kib_bound(purpose):
    # The largest supported mailbox, not a shorter convenient test address.
    recipient = "a" * 64 + "@" + ".".join(["b" * 63, "c" * 63, "d" * 61])
    assert len(recipient) == 254
    token = None if purpose == "password_changed" else TOKEN
    payload = render(purpose, recipient, token, ORIGIN)
    ident, lease = uuid.uuid4(), uuid.uuid4()
    digest = hashlib.sha256(recipient.encode()).digest()
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    nonce = b"N" * 12
    raw = json.dumps(payload, separators=(",", ":")).encode()
    ciphertext = nonce + AESGCM(POLICY.key).encrypt(
        nonce, raw, _aad(ident, purpose, digest, expiry)
    )
    assert len(ciphertext) <= 4096
    job = MailJob(ident, purpose, digest, ciphertext, expiry, lease, 1)
    assert open_job(job, POLICY) == payload


@pytest.mark.parametrize(
    "change",
    [
        "html_token",
        "html_origin",
        "html_extra_link",
        "html_script",
        "text_token",
        "purpose",
        "origin",
        "version",
        "extra_field",
        "missing_html",
        "non_string",
    ],
)
def test_authenticated_branded_content_cannot_diverge_from_exact_template(change):
    payload = deepcopy(render("verify_email", RECIPIENT, TOKEN, ORIGIN))
    if change == "html_token":
        payload["html"] = payload["html"].replace(TOKEN, "N" * 43)
    elif change == "html_origin":
        payload["html"] = payload["html"].replace(ORIGIN, "https://elsewhere.invalid")
    elif change == "html_extra_link":
        payload["html"] += '<a href="https://elsewhere.invalid">Click</a>'
    elif change == "html_script":
        payload["html"] += "<script>alert(1)</script>"
    elif change == "text_token":
        payload["text"] = payload["text"].replace(TOKEN, "N" * 43)
    elif change == "purpose":
        payload["purpose"] = "reset_password"
    elif change == "origin":
        payload["origin"] = "https://elsewhere.invalid"
    elif change == "version":
        payload["template_version"] = "unreviewed-version"
    elif change == "extra_field":
        payload["tracking"] = "true"
    elif change == "missing_html":
        del payload["html"]
    else:
        payload["html"] = None
    with pytest.raises(MailUnavailable):
        validate("verify_email", payload, ORIGIN)


@pytest.mark.parametrize(
    "origin", ['https://aqua-ai.us"', "https://aqua-ai.us/<script>", "javascript:x"]
)
def test_markup_and_insecure_origins_cannot_enter_a_template(origin):
    with pytest.raises(MailUnavailable):
        render("verify_email", RECIPIENT, TOKEN, origin)


@pytest.mark.parametrize("purpose", PURPOSES)
def test_original_plain_envelopes_remain_valid_without_rewriting_them(purpose):
    payload = render(
        purpose, RECIPIENT, None if purpose == "password_changed" else TOKEN, ORIGIN
    )
    legacy = {key: payload[key] for key in ("to", "subject", "text")}
    if purpose == "password_changed":
        legacy["text"] = NOTICE
    before = json.dumps(legacy, separators=(",", ":"))
    validate(purpose, legacy, ORIGIN)
    assert json.dumps(legacy, separators=(",", ":")) == before
