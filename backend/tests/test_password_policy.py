"""Password input and encoded-cost regressions need no external service."""

import pytest
from types import SimpleNamespace

from auth.config import AuthDenied
from auth import password_blocklist, password_hash
from auth.password_hash import DUMMY, PasswordHasher
from auth.password_policy import PasswordPolicy, normalize_email, normalize_password


@pytest.mark.parametrize(
    "value",
    [
        "short",
        "a" * 129,
        "has\x00control and length",
        "x" * 15,
        "123456789012345",
        "correct horse battery staple",
        "password123456789",
    ],
)
def test_weak_or_unsupported_passwords_are_rejected(value):
    with pytest.raises(AuthDenied, match="password_invalid"):
        normalize_password(value)


def test_nfc_spaces_managers_and_long_inputs_have_one_consistent_value():
    assert normalize_password(
        "an actual caf\u00e9 passphrase 81"
    ) == normalize_password("an actual cafe\u0301 passphrase 81")
    assert normalize_password("  paste this 128 character password!  ").startswith("  ")
    assert len(normalize_password("abc " * 32)) == 128
    assert normalize_password("caf\u00e9" * 32) == normalize_password("cafe\u0301" * 32)
    assert normalize_password("correct horse battery staple", establish=False)


@pytest.mark.parametrize(
    "value",
    [
        "abc@domain",
        "a..b@example.invalid",
        ".a@example.invalid",
        "a.@example.invalid",
        "a@-example.invalid",
        "a@example..invalid",
        "a\n@example.invalid",
        "a@caf\u00e9.invalid",
        "\u00e9@example.invalid",
        "x" * 65 + "@example.invalid",
    ],
)
def test_conservative_ascii_mail_policy_rejects_ambiguous_inputs(value):
    with pytest.raises(AuthDenied, match="email_invalid"):
        normalize_email(value)


def test_email_policy_preserves_plus_and_dot_but_matches_existing_case_policy():
    assert (
        normalize_email("First.Last+Tag@EXAMPLE.INVALID")
        == "first.last+tag@example.invalid"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_hashes", 3),
        ("max_hashes", True),
        ("verification_seconds", 86401),
        ("reset_seconds", 1801),
        ("window_seconds", 0),
        ("max_challenges", 1000000),
    ],
)
def test_operator_policy_cannot_disable_resource_bounds(field, value):
    with pytest.raises(ValueError):
        PasswordPolicy(**{field: value})


def test_pinned_offline_corpus_blocks_long_common_values_and_case_variants():
    assert len(password_blocklist.common_digests()) == 10898
    for public_common_value in (
        "starwarsstarwars",
        "STARWARSSTARWARS",
        "thisismypassword",
        "12345678910111213",
    ):
        with pytest.raises(AuthDenied, match="password_invalid"):
            normalize_password(public_common_value)
    assert normalize_password("a fresh unrelated fixture passphrase 71")


def test_corrupt_or_missing_blocklist_fails_closed_without_breaking_existing_login_policy(
    monkeypatch, tmp_path
):
    original = password_blocklist.SOURCE
    changed = tmp_path / "tampered-digests.txt"
    changed.write_text("0" * 64 + "\n", encoding="ascii")
    try:
        for path in (changed, tmp_path / "missing.txt"):
            password_blocklist.common_digests.cache_clear()
            monkeypatch.setattr(password_blocklist, "SOURCE", path)
            with pytest.raises(AuthDenied, match="password_policy_unavailable"):
                normalize_password("a fresh unrelated fixture passphrase 71")
            assert normalize_password(
                "a fresh unrelated fixture passphrase 71", establish=False
            )
    finally:
        monkeypatch.setattr(password_blocklist, "SOURCE", original)
        password_blocklist.common_digests.cache_clear()


def test_argon2_salt_policy_and_unicode_roundtrip():
    hasher = PasswordHasher()
    value = normalize_password("a fresh caf\u00e9 passphrase 81")
    first, second = hasher.hash(value), hasher.hash(value)
    assert first != second and first.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert hasher.verify(normalize_password("a fresh cafe\u0301 passphrase 81"), first)
    assert not hasher.verify("an incorrect password 81", first)
    assert not hasher.verify(value, None)
    assert not hasher.needs_rehash(first)


@pytest.mark.parametrize(
    "encoded",
    [
        None,
        "not an encoded hash",
        DUMMY.replace("m=19456", "m=999999999"),
        DUMMY.replace("m=19456", "m=8192"),
        DUMMY.replace("t=2", "t=1"),
        DUMMY.replace("t=2", "t=1000"),
        DUMMY.replace("p=1", "p=512"),
    ],
    ids=[
        "absent",
        "invalid-encoding",
        "excessive-memory",
        "unreviewed-low-memory",
        "unreviewed-low-iterations",
        "excessive-iterations",
        "excessive-parallelism",
    ],
)
def test_corrupted_hash_costs_do_dummy_work_without_allocating_requested_cost(
    monkeypatch, encoded
):
    seen = []
    real_verify = password_hash.ARGON.verify

    def verify(chosen, password):
        seen.append(chosen)
        # An observed regression must fail before requesting attacker-selected
        # memory/CPU costs. Supported dummy verification still executes CFFI.
        assert chosen == DUMMY
        return real_verify(chosen, password)

    monkeypatch.setattr(password_hash, "ARGON", SimpleNamespace(verify=verify))
    assert not PasswordHasher().verify("a fixture password 11", encoded)
    assert seen == [DUMMY]
