"""Bounded owner/purpose HMAC cursors contain no downloadable bearer authority."""

import base64
from datetime import datetime
import hashlib
import hmac
import json

from privacy.policy import CURSOR, identifier
from workspace.errors import WorkspaceError


class Cursors:
    def __init__(self, secret, owner):
        self.key = secret.encode()
        self.owner = identifier(owner)

    def encode(self, rank, at, item):
        data = json.dumps(
            [1, "private-export-list", self.owner, rank, at.isoformat(), str(item)],
            separators=(",", ":"),
        ).encode()
        digest = hmac.new(
            self.key, b"aqua-export-cursor-v1\0" + data, hashlib.sha256
        ).digest()
        return "v1." + base64.urlsafe_b64encode(data + digest).decode().rstrip("=")

    def decode(self, value):
        if value is None:
            return None
        try:
            if (
                type(value) is not str
                or not CURSOR.fullmatch(value)
                or not value.startswith("v1.")
            ):
                raise ValueError
            token = value[3:]
            raw = base64.b64decode(
                token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
            )
            data, digest = raw[:-32], raw[-32:]
            if not hmac.compare_digest(
                digest,
                hmac.new(
                    self.key, b"aqua-export-cursor-v1\0" + data, hashlib.sha256
                ).digest(),
            ):
                raise ValueError
            found = json.loads(data)
            if (
                not isinstance(found, list)
                or len(found) != 6
                or found[:3] != [1, "private-export-list", self.owner]
                or type(found[3]) is not int
                or found[3] not in (0, 1)
            ):
                raise ValueError
            at = datetime.fromisoformat(found[4])
            if at.tzinfo is None:
                raise ValueError
            return found[3], at, identifier(found[5])
        except (ValueError, TypeError, IndexError, UnicodeError):
            raise WorkspaceError("invalid_cursor", 422) from None
