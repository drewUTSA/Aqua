"""Pinned, local common-password digests; never query a user's password online."""

from functools import lru_cache
import hashlib
from pathlib import Path

from auth.config import AuthDenied

# SecLists MIT data, pinned c205c36a445bff37f8e58a9ec829105cd4975c58.
# Source/filter/hash provenance and the required license ship beside this file.
# Of 1,000,000 common passwords, 10,898 unique NFC/casefold values meet our
# 15..128-character bounds. This subset does not cover every compromised secret.
SOURCE = Path(__file__).with_name("password_blocklist_sha256.txt")
CORPUS_SHA256 = "a5b8b74b66c0ed54d90098285cb0dbe02217ae41d7c91f0c57cf4a761e14521a"
CORPUS_BYTES = 708370
CORPUS_ENTRIES = 10898


@lru_cache(maxsize=1)
def common_digests() -> frozenset[str]:
    try:
        with SOURCE.open("rb") as stream:
            raw = stream.read(CORPUS_BYTES + 1)
        if len(raw) != CORPUS_BYTES or hashlib.sha256(raw).hexdigest() != CORPUS_SHA256:
            raise ValueError
        entries = frozenset(raw.decode("ascii").splitlines())
        if len(entries) != CORPUS_ENTRIES or any(len(value) != 64 for value in entries):
            raise ValueError
        return entries
    except (OSError, UnicodeError, ValueError):
        raise AuthDenied("password_policy_unavailable") from None


def is_common(value: str) -> bool:
    return (
        hashlib.sha256(value.casefold().encode("utf-8")).hexdigest() in common_digests()
    )
