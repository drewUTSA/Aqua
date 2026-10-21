"""Synthetic-only helpers decrypt fake outbox jobs, never send them."""

from dataclasses import replace
import hashlib
import re
import uuid

from auth.config import AuthPolicy
from auth.mailconfig import MailPolicy
from auth.mailoutbox import MailJob, open_job
from auth.password_policy import PasswordPolicy
from auth.passwords import PasswordStore
from nl2sql.config import Settings

EMAIL = "password.fixture@example.invalid"
PASSWORD = "A synthetic fixture password 78!"
NEW_PASSWORD = "Another synthetic fixture password 91!"
MAIL = MailPolicy(enabled=True, key=bytes(range(32)))
SETTINGS = Settings()


def digest() -> bytes:
    return hashlib.sha256(uuid.uuid4().bytes).digest()


def service(storage, **changes) -> PasswordStore:
    policy = PasswordPolicy(
        login_peer_limit=100,
        login_global_limit=100,
        login_address_limit=100,
        mail_peer_limit=100,
        mail_global_limit=100,
        mail_address_limit=100,
        consume_peer_limit=100,
        consume_global_limit=100,
    )
    return PasswordStore(storage, AuthPolicy(), replace(policy, **changes), MAIL)


def messages(storage, purpose: str) -> list[dict[str, str]]:
    with storage.transaction() as conn:
        rows = conn.execute(
            "SELECT id,purpose,recipient_digest,ciphertext,expires_at FROM app.account_mail "
            "WHERE purpose=%s ORDER BY created_at,id",
            (purpose,),
        ).fetchall()
    return [
        open_job(
            MailJob(
                row[0], row[1], bytes(row[2]), bytes(row[3]), row[4], uuid.uuid4(), 0
            ),
            MAIL,
        )
        for row in rows
    ]


def email_token(storage, purpose: str) -> str:
    return re.search(
        r"#token=([A-Za-z0-9_-]{43})", messages(storage, purpose)[-1]["text"]
    )[1]


def register(store, email: str = EMAIL, password: str = PASSWORD) -> tuple[str, str]:
    store.request_email(email, "verify_email", "fixture")
    token = email_token(store.storage, "verify_email")
    return store.complete_verification(token, password, "fixture"), token


def login(store, email: str = EMAIL, password: str = PASSWORD):
    token = digest()
    return token, store.login(email, password, token, digest(), "fixture", SETTINGS)
