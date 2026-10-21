"""Synthetic encrypted envelopes must still obey the exact account-mail contract."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

from auth.mailconfig import MailPolicy, MailUnavailable
from auth.mailoutbox import MailJob, _aad, open_job

POLICY = MailPolicy(True, b"K" * 32)
TOKEN = "M" * 43
RECIPIENT = "fixture@example.invalid"


def _sealed(payload, purpose="verify_email"):
    ident = uuid.uuid4()
    digest = hashlib.sha256(payload["to"].encode()).digest()
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    nonce = uuid.uuid4().bytes[:12]
    ciphertext = nonce + AESGCM(POLICY.key).encrypt(
        nonce, json.dumps(payload).encode(), _aad(ident, purpose, digest, expiry)
    )
    return MailJob(ident, purpose, digest, ciphertext, expiry, uuid.uuid4(), 1)


@pytest.mark.parametrize(
    "origin",
    [
        "https://aqua-ai.\nus",
        "https://aqua-ai.\tus",
        "https://aqua-ai.us\\evil.invalid",
        "https://aqua-ai.us bad",
    ],
)
def test_account_mail_rejects_raw_control_backslash_or_invalid_origin(origin):
    with pytest.raises(MailUnavailable):
        MailPolicy(True, POLICY.key, origin)


@pytest.mark.parametrize(
    "change",
    ["wrong_subject", "extra_link", "wrong_origin", "wrong_path", "display_recipient"],
)
def test_authenticated_envelope_cannot_change_template_link_or_recipient_syntax(change):
    payload = {
        "to": RECIPIENT,
        "subject": "AQUA: Verify your email",
        "text": "Verify your email using this link:\nhttps://aqua-ai.us/verify-email#token="
        + TOKEN
        + "\nIf you did not request this, ignore this message.",
    }
    if change == "wrong_subject":
        payload["subject"] = "AQUA password changed"
    elif change == "extra_link":
        payload["text"] += "\nVisit https://unrelated.example.invalid/"
    elif change == "wrong_origin":
        payload["text"] = payload["text"].replace(
            "https://aqua-ai.us", "https://unrelated.example.invalid"
        )
    elif change == "wrong_path":
        payload["text"] = payload["text"].replace("/verify-email", "/reset-password")
    else:
        payload["to"] = "Display<fixture@example.invalid>"
    with pytest.raises(MailUnavailable):
        open_job(_sealed(payload), POLICY)
