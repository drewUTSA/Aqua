"""Signed bounded cursors bind owner, list filters and stable sort position."""

import base64
import hashlib
import hmac
import json
from datetime import datetime
from uuid import UUID

from workspace.errors import WorkspaceError


def fingerprint(value: dict) -> bytes:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).digest()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


class Cursors:
    def __init__(self, secret: str, owner: str, scope: dict) -> None:
        self.key = hmac.digest(secret.encode(), b"aqua-workspace-cursor-v1", "sha256")
        self.scope = fingerprint({"owner": owner, **scope}).hex()

    def encode(self, position: list) -> str:
        raw = json.dumps(
            {"v": 1, "scope": self.scope, "p": position},
            separators=(",", ":"),
            default=str,
        ).encode()
        return _encode(raw) + "." + _encode(hmac.digest(self.key, raw, "sha256"))

    def decode(self, value: str | None, *, messages: bool = False) -> list | None:
        if value is None:
            return None
        try:
            if len(value) > 1024 or not value.isascii():
                raise ValueError
            data, signature = value.split(".")
            raw = base64.b64decode(
                data + "=" * (-len(data) % 4), altchars=b"-_", validate=True
            )
            expected = _encode(hmac.digest(self.key, raw, "sha256"))
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            body = json.loads(raw)
            if (
                set(body) != {"v", "scope", "p"}
                or body["v"] != 1
                or body["scope"] != self.scope
            ):
                raise ValueError
            position = body["p"]
            if messages:
                if (
                    not isinstance(position, list)
                    or len(position) != 1
                    or type(position[0]) is not int
                    or position[0] < 1
                ):
                    raise ValueError
            else:
                if (
                    not isinstance(position, list)
                    or len(position) != 2
                    or datetime.fromisoformat(position[0]).tzinfo is None
                ):
                    raise ValueError
                UUID(position[1])
            return position
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise WorkspaceError("invalid_cursor", 422) from None
