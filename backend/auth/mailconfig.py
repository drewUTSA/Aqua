"""Reviewed account-mail configuration; no provider key belongs in the web process."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import base64
import os
from urllib.parse import urlsplit

from nl2sql.auth_config import normalize_app_origin


class MailUnavailable(RuntimeError):
    """Fixed failure category: never carry an address, key, token or driver detail."""


@dataclass(frozen=True)
class MailPolicy:
    enabled: bool = False
    key: bytes = field(default=b"", repr=False)
    public_origin: str = "https://aqua-ai.us"
    max_rows: int = 4096
    max_pending: int = 2048
    cleanup_batch: int = 64

    def __post_init__(self) -> None:
        try:
            if normalize_app_origin(self.public_origin) != self.public_origin:
                raise ValueError
            origin = urlsplit(self.public_origin)
            port = origin.port
        except (TypeError, ValueError):
            raise MailUnavailable("account_mail_configuration_invalid") from None
        if (
            type(self.enabled) is not bool
            or (self.enabled and (type(self.key) is not bytes or len(self.key) != 32))
            or origin.scheme != "https"
            or not origin.hostname
            or origin.username is not None
            or origin.password is not None
            or origin.path not in {"", "/"}
            or origin.query
            or origin.fragment
            or port not in {None, 443}
            or any(
                type(value) is not int
                for value in (self.max_pending, self.max_rows, self.cleanup_batch)
            )
            or not 1 <= self.max_pending <= self.max_rows <= 4096
            or not 1 <= self.cleanup_batch <= 128
        ):
            raise MailUnavailable("account_mail_configuration_invalid")


def load_mail_policy(environ: Mapping[str, str] | None = None) -> MailPolicy:
    env = os.environ if environ is None else environ
    enabled = env.get("ACCOUNT_MAIL_ENABLED", "false")
    try:
        if enabled not in {"true", "false"}:
            raise ValueError
        key = env.get("ACCOUNT_MAIL_OUTBOX_KEY", "")
        return MailPolicy(
            enabled=enabled == "true",
            key=base64.b64decode(key, altchars=b"-_", validate=True) if key else b"",
            public_origin=env.get("ACCOUNT_PUBLIC_ORIGIN", "https://aqua-ai.us"),
        )
    except (ValueError, TypeError):
        raise MailUnavailable("account_mail_configuration_invalid") from None
