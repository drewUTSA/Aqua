"""Compile explicitly reviewed, dataset-bound SELECT examples without network I/O."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from sqlglot import exp

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from nl2sql.validate import UnsafeQueryError, validate_sql  # noqa: E402

MAX_BYTES = 262144
MAX_EXAMPLES = 64


class PackDenied(ValueError):
    """Safe fixed-category errors never echo source questions or SQL."""


def unique(items):
    result = {}
    for key, value in items:
        if key in result:
            raise PackDenied("duplicate_field")
        result[key] = value
    return result


def allowlist_hash(tables) -> str:
    return hashlib.sha256(
        json.dumps(sorted(tables), separators=(",", ":")).encode()
    ).hexdigest()


def bounded_text(value, maximum: int) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return 0 < len(value.encode("utf-8")) <= maximum
    except UnicodeError:
        return False


def compile_pack(
    raw: bytes, *, reviewed_sha256: str, dataset: str, allowed_tables: frozenset[str]
) -> bytes:
    if (
        len(raw) > MAX_BYTES
        or not re.fullmatch(r"[a-f0-9]{64}", reviewed_sha256)
        or hashlib.sha256(raw).hexdigest() != reviewed_sha256
    ):
        raise PackDenied("review_binding_invalid")
    try:
        pack = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        raise PackDenied("pack_invalid") from None
    required = {"schemaVersion", "approved", "dataset", "allowlist_sha256", "examples"}
    if (
        type(pack) is not dict
        or set(pack) != required
        or type(pack["schemaVersion"]) is not int
        or pack["schemaVersion"] != 1
        or pack["approved"] is not True
    ):
        raise PackDenied("review_required")
    if (
        not allowed_tables
        or pack["dataset"] != dataset
        or pack["allowlist_sha256"] != allowlist_hash(allowed_tables)
    ):
        raise PackDenied("dataset_scope_invalid")
    examples = pack["examples"]
    if type(examples) is not list or not 1 <= len(examples) <= MAX_EXAMPLES:
        raise PackDenied("example_budget_invalid")
    identifiers, questions, compiled = set(), set(), []
    for item in examples:
        if (
            type(item) is not dict
            or set(item) != {"id", "split", "question", "sql", "tables"}
            or item["split"] != "train"
        ):
            raise PackDenied("training_split_required")
        key, question, sql, tables = (
            item[name] for name in ("id", "question", "sql", "tables")
        )
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key)
            or key in identifiers
        ):
            raise PackDenied("example_identity_invalid")
        if (
            not isinstance(question, str)
            or not bounded_text(question, 8000)
            or not question.strip()
            or len(question) > 2000
            or question.strip().casefold() in questions
        ):
            raise PackDenied("question_invalid")
        if (
            not bounded_text(sql, 16384)
            or type(tables) is not list
            or not 1 <= len(tables) <= 8
            or not all(type(name) is str for name in tables)
            or len(set(tables)) != len(tables)
            or not set(tables) <= allowed_tables
        ):
            raise PackDenied("declared_scope_invalid")
        try:
            tree = validate_sql(sql, allowed_tables=set(tables))
        except (UnsafeQueryError, ValueError):
            raise PackDenied("sql_invalid") from None
        actual = {
            table.name.lower() for table in tree.find_all(exp.Table)
        } & allowed_tables
        if actual != set(tables):
            raise PackDenied("declared_scope_invalid")
        identifiers.add(key)
        questions.add(question.strip().casefold())
        compiled.append(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    return ("\n".join(compiled) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--reviewed-sha256", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument(
        "--tables", required=True, help="Reviewed comma-separated table allowlist"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional create-only private JSONL; default is dry-run",
    )
    args = parser.parse_args()
    try:
        with args.input.open("rb") as source:
            raw = source.read(MAX_BYTES + 1)
        artifact = compile_pack(
            raw,
            reviewed_sha256=args.reviewed_sha256,
            dataset=args.dataset,
            allowed_tables=frozenset(args.tables.split(",")),
        )
        if args.output:
            descriptor = os.open(
                args.output,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(artifact)
                output.flush()
                os.fsync(output.fileno())
        print(
            json.dumps(
                {
                    "status": "prepared",
                    "examples": len(artifact.splitlines()),
                    "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
                    "written": args.output is not None,
                    "network_calls": 0,
                    "database_writes": 0,
                }
            )
        )
        return 0
    except (PackDenied, OSError) as error:
        print(
            json.dumps(
                {
                    "status": "denied",
                    "category": (
                        str(error)
                        if isinstance(error, PackDenied)
                        else "file_unavailable"
                    ),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
