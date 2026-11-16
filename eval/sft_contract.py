"""Offline review/split contracts for Aqua-only future supervised SQL examples."""

import hashlib
import json
import re
import unicodedata

from eval.knowledge_pack import (
    MAX_BYTES,
    MAX_EXAMPLES,
    PackDenied,
    allowlist_hash,
    bounded_text,
    compile_pack,
    unique,
)
from eval.compare_runs import MAX_BYTES as HOLDOUT_BYTES, MAX_CASES, records, indexed
from nl2sql.validate import UnsafeQueryError, validate_sql


class ExportDenied(ValueError):
    """Only fixed categories cross the export boundary."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def reviewed(raw: bytes, expected: str, maximum: int) -> None:
    if (
        type(expected) is not str
        or not re.fullmatch(r"[a-f0-9]{64}", expected)
        or not 0 < len(raw) <= maximum
        or digest(raw) != expected
    ):
        raise ExportDenied("reviewed_bytes_required")


def question_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    cleaned = "".join(
        " " if c.isspace() else c
        for c in normalized
        if not unicodedata.category(c).startswith("C") or c.isspace()
    )
    return " ".join(re.findall(r"\w+", cleaned))


def sql_key(sql: str, tables: frozenset[str]) -> str:
    try:
        tree = validate_sql(sql, allowed_tables=tables)
        return tree.sql(dialect="postgres", normalize=True, comments=False)
    except (UnsafeQueryError, ValueError, TypeError, RecursionError):
        # The validator's exceptions may explain supplied SQL. Keep them private.
        raise ExportDenied("sql_scope_invalid") from None


def provenance(value: dict) -> None:
    required = {
        "source_id",
        "revision",
        "rights",
        "license",
        "reviewed_for_sft",
        "aqua_or_public_only",
        "no_company_data",
        "semantic_leakage_reviewed",
    }
    if type(value) is not dict or set(value) != required:
        raise ExportDenied("provenance_required")
    if (
        type(value["rights"]) is not str
        or value["rights"] not in {"aqua_owned", "public_permitted"}
        or any(
            value[k] is not True
            for k in (
                "reviewed_for_sft",
                "aqua_or_public_only",
                "no_company_data",
                "semantic_leakage_reviewed",
            )
        )
    ):
        raise ExportDenied("rights_and_review_declarations_required")
    for name in ("source_id", "revision", "license"):
        if not bounded_text(value[name], 256) or not value[name].strip():
            raise ExportDenied("provenance_invalid")


def source(
    raw: bytes, sha: str, dataset: str, tables: frozenset[str], schema_sha: str
) -> tuple[list[dict], dict]:
    reviewed(raw, sha, MAX_BYTES)
    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        raise ExportDenied("source_json_invalid") from None
    required = {
        "schemaVersion",
        "approved",
        "dataset",
        "allowlist_sha256",
        "schema_sha256",
        "provenance",
        "examples",
    }
    if (
        type(value) is not dict
        or set(value) != required
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["approved"] is not True
    ):
        raise ExportDenied("reviewed_source_required")
    if (
        value["dataset"] != dataset
        or value["allowlist_sha256"] != allowlist_hash(tables)
        or value["schema_sha256"] != schema_sha
    ):
        raise ExportDenied("source_scope_mismatch")
    provenance(value["provenance"])
    examples = value["examples"]
    if (
        type(examples) is not list
        or not 2 <= len(examples) <= MAX_EXAMPLES
        or any(
            type(c) is not dict
            or type(c.get("split")) is not str
            or c["split"] not in {"train", "validation"}
            for c in examples
        )
    ):
        raise ExportDenied("source_split_invalid")
    if {c["split"] for c in examples} != {"train", "validation"}:
        raise ExportDenied("both_partitions_required")
    return examples, value["provenance"]


def compile_partitions(
    examples: list[dict], dataset: str, tables: frozenset[str]
) -> tuple[dict, dict]:
    compiled, conversions = {}, {}
    for partition in ("train", "validation"):
        # Source review is already bound above. This deterministic adaptation
        # reuses the existing training-only compiler's structural/SQL checks;
        # its computed digest does not attest a new independent human review.
        items = [dict(c, split="train") for c in examples if c["split"] == partition]
        converted = json.dumps(
            {
                "schemaVersion": 1,
                "approved": True,
                "dataset": dataset,
                "allowlist_sha256": allowlist_hash(tables),
                "examples": items,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        try:
            artifact = compile_pack(
                converted,
                reviewed_sha256=digest(converted),
                dataset=dataset,
                allowed_tables=tables,
            )
        except (PackDenied, ValueError, TypeError):
            raise ExportDenied("compiled_source_invalid") from None
        compiled[partition] = [json.loads(line) for line in artifact.splitlines()]
        conversions[partition] = digest(converted)
    return compiled, conversions


def exclude_holdout(
    examples: list[dict], raw: bytes, sha: str, tables: frozenset[str]
) -> int:
    reviewed(raw, sha, HOLDOUT_BYTES)
    try:
        heldout = records(raw)
        indexed(heldout)
    except ValueError:
        raise ExportDenied("holdout_invalid") from None
    if not 1 <= len(heldout) <= MAX_CASES:
        raise ExportDenied("holdout_budget_invalid")
    seen = [set(), set(), set()]
    allowed = {
        "id",
        "split",
        "question",
        "sql",
        "tables",
        "difficulty",
        "ordered",
        "rule",
    }
    for is_holdout, case in [(True, c) for c in heldout] + [
        (False, c) for c in examples
    ]:
        if (
            type(case) is not dict
            or not set(case) <= allowed
            or not {"id", "split", "question", "sql"} <= set(case)
            or not bounded_text(case["id"], 128)
            or not bounded_text(case["question"], 8000)
            or not bounded_text(case["sql"], 16384)
        ):
            raise ExportDenied("case_contract_invalid")
        if "rule" in case and (
            type(case["rule"]) is not str
            or re.fullmatch(r"[a-z][a-z0-9_]{0,31}", case["rule"]) is None
        ):
            raise ExportDenied("holdout_rule_invalid")
        if is_holdout and case["split"] != "test":
            raise ExportDenied("independent_test_only_holdout_required")
        keys = (
            case["id"],
            question_key(case["question"]),
            sql_key(case["sql"], tables),
        )
        # Protected test records may cover the same question/SQL with distinct
        # IDs. Keep every record; all their forms still exclude export examples.
        # indexed() above continues to reject duplicate protected IDs.
        if not keys[1] or (
            not is_holdout and any(key in values for key, values in zip(keys, seen))
        ):
            raise ExportDenied("duplicate_or_holdout_leakage")
        for key, values in zip(keys, seen):
            values.add(key)
    return len(heldout)
