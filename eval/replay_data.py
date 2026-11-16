"""Closed synthetic replay records; these are not model-generated predictions."""

import hashlib
import json
import re

MAX_BYTES = 262144
FIELDS = {
    "id",
    "split",
    "dataset",
    "question",
    "sql",
    "tables",
    "nearest",
    "expected",
    "kind",
}
KINDS = {"answer", "scope_denial", "sql_denial"}


class ReplayDenied(ValueError):
    """A replay artifact violates its bounded, synthetic-only contract."""


def unique(pairs: list[tuple]) -> dict:
    """Ambiguous JSON must never acquire last-value-wins semantics."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReplayDenied("replay_duplicate_field")
        result[key] = value
    return result


def load(raw: bytes) -> tuple[list[dict], str]:
    """Validate every record, including excluded training entries, before use."""
    if not raw or len(raw) > MAX_BYTES:
        raise ReplayDenied("replay_byte_budget")
    try:
        cases = [
            json.loads(line, object_pairs_hook=unique)
            for line in raw.decode("utf-8").splitlines()
            if line.strip()
        ]
    except (UnicodeError, ValueError) as error:
        raise ReplayDenied("replay_json_invalid") from error
    if not 24 <= len(cases) <= 64:
        raise ReplayDenied("replay_case_budget")
    ids = set()
    for case in cases:
        if type(case) is not dict or set(case) != FIELDS:
            raise ReplayDenied("replay_fields_invalid")
        identifier = case["id"]
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"synthetic-[a-z0-9-]{1,60}", identifier)
            or identifier in ids
        ):
            raise ReplayDenied("replay_identity_invalid")
        ids.add(identifier)
        if (
            type(case["split"]) is not str
            or case["split"] not in {"train", "test"}
            or type(case["dataset"]) is not str
            or case["dataset"] not in {"bank", "pagila"}
            or type(case["kind"]) is not str
            or case["kind"] not in KINDS
        ):
            raise ReplayDenied("replay_scope_invalid")
        for field, maximum in (("question", 2000), ("sql", 2000)):
            value = case[field]
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > maximum
                or "\0" in value
            ):
                raise ReplayDenied("replay_text_invalid")
        for field, maximum in (("tables", 4), ("nearest", 4)):
            values = case[field]
            if (
                type(values) is not list
                or not 1 <= len(values) <= maximum
                or any(
                    not isinstance(v, str)
                    or not re.fullmatch(r"[a-z_]+(?:\.[a-z_]+)?", v)
                    for v in values
                )
                or len(set(values)) != len(values)
            ):
                raise ReplayDenied("replay_relations_invalid")
        expected = case["expected"]
        if (
            type(expected) is not list
            or len(expected) > 10
            or any(
                type(row) is not list
                or len(row) > 4
                or any(type(v) not in {int, str, type(None)} for v in row)
                for row in expected
            )
        ):
            raise ReplayDenied("replay_expected_invalid")
    if sum(c["split"] == "test" for c in cases) < 24 or not any(
        c["split"] == "train" for c in cases
    ):
        raise ReplayDenied("replay_split_invalid")
    return cases, hashlib.sha256(raw).hexdigest()
