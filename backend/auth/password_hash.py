"""Bounded Argon2id work, detached from PostgreSQL connection lifetimes."""

from contextlib import contextmanager
import base64
import binascii
import re
import threading
from collections.abc import Iterator

from argon2 import PasswordHasher as Argon2Hasher, Type
from argon2.exceptions import HashingError, InvalidHashError, VerificationError

from auth.config import AuthDenied, AuthLimited

# OWASP's Argon2id minimum, measured by the isolated release checks. A hash
# receives 19 MiB; global admission allows at most two active hash jobs.
MEMORY_KIB = 19456
ITERATIONS = 2
PARALLELISM = 1
# Future upgrades add their new tuple while retaining explicitly reviewed past
# tuples for rehash-on-success. Never accept arbitrary lower encoded costs.
REVIEWED_COSTS = frozenset({(MEMORY_KIB, ITERATIONS, PARALLELISM)})
ARGON = Argon2Hasher(
    time_cost=ITERATIONS,
    memory_cost=MEMORY_KIB,
    parallelism=PARALLELISM,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
DUMMY = ARGON.hash("fixture-independent timing work, never an account password")
LOCAL_SLOTS = threading.BoundedSemaphore(2)
ENCODED = re.compile(
    r"\$argon2id\$v=19\$m=([1-9][0-9]{0,5}),t=([1-9][0-9]{0,2}),p=([1-9][0-9]{0,2})"
    r"\$([A-Za-z0-9+/]{22})\$([A-Za-z0-9+/]{43})\Z"
)


@contextmanager
def local_slot() -> Iterator[None]:
    if not LOCAL_SLOTS.acquire(blocking=False):
        raise AuthLimited(1)
    try:
        yield
    finally:
        LOCAL_SLOTS.release()


class PasswordHasher:
    """Accept only reviewed encoded costs; database corruption cannot request GiB."""

    def hash(self, password: str) -> str:
        try:
            return ARGON.hash(password)
        except HashingError:
            raise AuthDenied("password_hash_unavailable") from None

    def verify(self, password: str, encoded: str | None) -> bool:
        chosen = encoded if self._supported(encoded) else DUMMY
        try:
            return bool(ARGON.verify(chosen, password) and chosen != DUMMY)
        except (VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, encoded: str) -> bool:
        return ARGON.check_needs_rehash(encoded)

    @staticmethod
    def _supported(encoded: str | None) -> bool:
        if not isinstance(encoded, str) or not 32 <= len(encoded) <= 1024:
            return False
        match = ENCODED.fullmatch(encoded)
        if match is None or tuple(map(int, match.groups()[:3])) not in REVIEWED_COSTS:
            return False
        try:
            # extract_parameters() alone accepts malformed alphabet/tail bits.
            # Require the canonical unpadded PHC representation before invoking
            # CFFI, otherwise a corrupted row could fail much faster than dummy
            # verification and violate the rejected-account work boundary.
            for part, size in zip(match.groups()[3:], (16, 32)):
                decoded = base64.b64decode(part + "=" * (-len(part) % 4), validate=True)
                if (
                    len(decoded) != size
                    or base64.b64encode(decoded).decode("ascii").rstrip("=") != part
                ):
                    return False
        except (binascii.Error, ValueError):
            return False
        return True
