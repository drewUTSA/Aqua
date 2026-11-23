"""Provision the disposable presenter account or serve the packaged Aqua application."""

import json
import os
from pathlib import Path
import re
import secrets
import sys

sys.path.insert(0, "/app")


def provision(config):
    import psycopg
    from auth.config import load_auth_policy
    from auth.mailconfig import MailPolicy
    from auth.mailqueue import MailOutbox
    from auth.mailworker import MailWorker
    from auth.passwords import PasswordStore
    from nl2sql.config import load_settings
    from storage.migrate import apply
    from storage.pool import Storage
    from storage.config import load_storage_settings

    with psycopg.connect(config["migrator"], autocommit=True) as conn:
        if apply(conn) != 10:
            raise RuntimeError("Unexpected application schema")
    settings = load_settings()
    policy = load_auth_policy(settings)
    mail = MailPolicy(
        enabled=True, key=secrets.token_bytes(32), public_origin=config["mail_origin"]
    )
    storage = Storage(load_storage_settings())
    password = secrets.token_urlsafe(30)
    email = "presenter@example.test"

    class Mailbox:
        def send(self, job_id, payload):
            if payload["to"] != email or payload["purpose"] != "verify_email":
                raise RuntimeError("Incorrect synthetic recipient")
            (self.token,) = re.findall(
                r"/verify-email#token=([A-Za-z0-9_-]{43})(?:\n|$)", payload["text"]
            )
            return "accepted"

    try:
        store = PasswordStore(storage, policy, mail_policy=mail)
        store.request_email(email, "verify_email", "presenter-setup")
        mailbox = Mailbox()
        if not MailWorker(MailOutbox(storage, mail), mailbox).once():
            raise RuntimeError("Presenter mailbox unavailable")
        owner = store.complete_verification(mailbox.token, password, "presenter-setup")
        with storage.transaction() as conn:
            conn.execute(
                "INSERT INTO app.dataset_grants(user_id,dataset_key) VALUES(%s,%s)",
                (owner, policy.dataset_key),
            )
        with psycopg.connect(settings.database_url) as reader:
            if reader.execute(
                "SELECT current_user,current_database(),current_setting('transaction_read_only')"
            ).fetchone() != ("aqua_sales_demo_reader", "aqua_sales_demo", "on"):
                raise RuntimeError("Incorrect sales connection")
            if reader.execute("SELECT count(*) FROM public.trans").fetchone() != (
                1000,
            ):
                raise RuntimeError("Incorrect sales snapshot")
    finally:
        storage.close()
    print(json.dumps({"email": email, "password": password}))


if __name__ == "__main__":
    if sys.argv[1] == "provision":
        config = json.load(sys.stdin)
        os.environ.update(config["environment"])
        provision(config)
    elif sys.argv[1] == "serve":
        ticket = Path("/tmp/service-env.json")
        os.environ.update(json.loads(ticket.read_bytes()))
        ticket.unlink()
        import uvicorn

        uvicorn.run(
            "main:app",
            host="127.0.0.1",
            port=8000,
            log_level="critical",
            access_log=False,
        )
