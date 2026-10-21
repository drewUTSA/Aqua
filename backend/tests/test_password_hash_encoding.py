"""Malformed PHC rows must execute real dummy work, not a fast parser rejection."""

import pytest
from types import SimpleNamespace

from auth import password_hash
from auth.password_hash import DUMMY, PasswordHasher

PREFIX, SALT, HASH = DUMMY.rsplit("$", 2)


@pytest.mark.parametrize(
    "encoded",
    [
        PREFIX + "$" + "!" * 22 + "$" + HASH,
        PREFIX + "$" + SALT + "$" + "!" * 43,
        PREFIX + "$" + "_" * 22 + "$" + HASH,
        PREFIX + "$" + SALT[:-1] + "B$" + HASH,
        PREFIX + "$" + SALT + "$" + HASH[:-1] + "B",
        DUMMY.replace("m=19456,t=2,p=1", "m=19456,t=2,p=1,m=19456"),
        DUMMY.replace("m=19456", "m=019456"),
        DUMMY.replace("v=19", "v=019"),
        DUMMY.replace("argon2id", "argon2i"),
        DUMMY + "\n",
    ],
    ids=[
        "invalid-salt-alphabet",
        "invalid-hash-alphabet",
        "url-alphabet",
        "noncanonical-salt-tail",
        "noncanonical-hash-tail",
        "duplicate-cost",
        "noncanonical-cost",
        "noncanonical-version",
        "different-algorithm",
        "trailing-newline",
    ],
)
def test_invalid_phc_encoding_uses_actual_dummy_hash(monkeypatch, encoded):
    real_verify = password_hash.ARGON.verify
    seen = []

    def observe(chosen, password):
        seen.append(chosen)
        return real_verify(chosen, password)

    monkeypatch.setattr(password_hash, "ARGON", SimpleNamespace(verify=observe))
    assert not PasswordHasher().verify(
        "unrelated synthetic fixture password 31!", encoded
    )
    assert seen == [DUMMY]


def test_canonical_current_encoding_uses_the_account_hash(monkeypatch):
    hasher = PasswordHasher()
    password = "canonical synthetic fixture password 32!"
    encoded = hasher.hash(password)
    real_verify = password_hash.ARGON.verify
    seen = []

    def observe(chosen, value):
        seen.append(chosen)
        return real_verify(chosen, value)

    monkeypatch.setattr(password_hash, "ARGON", SimpleNamespace(verify=observe))
    assert hasher.verify(password, encoded)
    assert seen == [encoded]
