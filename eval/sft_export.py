"""Dry-run by default: reviewed Aqua/public examples to future SQL SFT artifacts."""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from eval.sft_contract import (  # noqa: E402
    ExportDenied,
    MAX_BYTES,
    HOLDOUT_BYTES,
    compile_partitions,
    digest,
    exclude_holdout,
    reviewed,
    source,
)
from eval.knowledge_pack import allowlist_hash  # noqa: E402
from nl2sql.answer_size import answer_size  # noqa: E402
from nl2sql.control import CURRENT  # noqa: E402
from nl2sql.generate import (  # noqa: E402
    SYSTEM_INSTRUCTION,
    SQL_REPLY_SCHEMA,
    build_prompt,
)
from nl2sql import generate  # noqa: E402

MODEL = {
    "repository": "Qwen/Qwen3-4B",
    "revision": "1cfa9a7208912126459214e8b04321603b3df60c",
    "declared_license": "Apache-2.0",
    "model_bytes_verified": False,
    "enable_thinking": False,
}
MAX_OUTPUT = 8 * 1024 * 1024


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


@dataclass(frozen=True)
class Artifacts:
    training: bytes
    validation: bytes
    manifest: bytes


def prepare(
    raw: bytes,
    schema: bytes,
    holdout: bytes,
    *,
    source_sha256: str,
    schema_sha256: str,
    holdout_sha256: str,
    dataset: str,
    allowed_tables: frozenset[str],
) -> Artifacts:
    """No providers, databases, tokenizer, weights or training packages are used."""
    if (
        not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", dataset)
        or not 1 <= len(allowed_tables) <= 64
        or any(
            type(t) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", t)
            for t in allowed_tables
        )
    ):
        raise ExportDenied("dataset_allowlist_invalid")
    reviewed(schema, schema_sha256, 65536)
    try:
        schema_text = schema.decode("utf-8")
    except UnicodeError:
        raise ExportDenied("schema_text_invalid") from None
    if not schema_text.strip() or "\0" in schema_text:
        raise ExportDenied("schema_text_invalid")
    examples, declaration = source(
        raw, source_sha256, dataset, allowed_tables, schema_sha256
    )
    partitions, conversions = compile_partitions(examples, dataset, allowed_tables)
    holdout_count = exclude_holdout(examples, holdout, holdout_sha256, allowed_tables)
    outputs, identities = {}, []
    # build_prompt otherwise consults CURRENT for private conversation context.
    # A standalone export must never inherit that ambient owner/history state.
    token = CURRENT.set(None)
    try:
        for partition, cases in partitions.items():
            lines = []
            for case in cases:
                question = case["question"].strip()
                prompt = build_prompt(
                    question, schema_text, size=answer_size(question).instruction
                )
                if len(prompt.encode()) + len(SYSTEM_INSTRUCTION.encode()) > 65536:
                    raise ExportDenied("production_prompt_budget")
                row = canonical(
                    {
                        "messages": [
                            {"role": "system", "content": SYSTEM_INSTRUCTION},
                            {"role": "user", "content": prompt},
                            {
                                "role": "assistant",
                                "content": canonical(
                                    {"sql": case["sql"].strip()}
                                ).decode(),
                            },
                        ]
                    }
                )
                lines.append(row)
                identities.append(
                    {
                        "id_sha256": digest(case["id"].encode()),
                        "partition": partition,
                        "record_sha256": digest(row),
                    }
                )
            outputs[partition] = b"\n".join(lines) + b"\n"
    finally:
        CURRENT.reset(token)
    if sum(map(len, outputs.values())) > MAX_OUTPUT:
        raise ExportDenied("export_output_budget")
    manifest = {
        "schema_version": 1,
        "kind": "reviewed_aqua_sql_sft_export_foundation",
        "dataset": dataset,
        "model": MODEL,
        "source_reviewed_sha256": source_sha256,
        "schema_reviewed_sha256": schema_sha256,
        "holdout_reviewed_sha256": holdout_sha256,
        "allowlist_sha256": allowlist_hash(allowed_tables),
        "provenance_declaration_sha256": digest(canonical(declaration)),
        "declarations_attested": False,
        "schema_origin_attested": False,
        "execution_correctness_verified": False,
        "semantic_leakage_attested": False,
        "converted_compiler_input_sha256": conversions,
        "conversion_review": "deterministic_conversion_not_independent_human_attestation",
        "holdout_cases_excluded": holdout_count,
        "duplicate_guards": [
            "id",
            "nfkc_casefold_question_words",
            "validated_canonical_sql",
        ],
        "training_cases": len(partitions["train"]),
        "validation_cases": len(partitions["validation"]),
        "training_sha256": digest(outputs["train"]),
        "validation_sha256": digest(outputs["validation"]),
        "production_generator_source_sha256": digest(
            Path(generate.__file__).read_bytes()
        ),
        "response_schema_sha256": digest(canonical(SQL_REPLY_SCHEMA)),
        "answer_size_rules": True,
        "records": identities,
        "tokenized": False,
        "adequate_training_corpus_claimed": False,
        "network_calls": 0,
        "database_calls": 0,
        "training_performed": False,
    }
    return Artifacts(
        outputs["train"], outputs["validation"], canonical(manifest) + b"\n"
    )


def write(artifacts: Artifacts, output: Path) -> None:
    """A new directory only; a partial failure never creates a complete manifest."""
    output = output.resolve()
    if output.is_relative_to(ROOT.resolve()):
        raise ExportDenied("output_must_be_outside_application")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, raw in (
        ("train.jsonl", artifacts.training),
        ("validation.jsonl", artifacts.validation),
        ("manifest.json", artifacts.manifest),
    ):
        fd = os.open(
            output / name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "wb") as destination:
            destination.write(raw)
            destination.flush()
            os.fsync(destination.fileno())


def bounded(path: Path, maximum: int) -> bytes:
    with path.open("rb") as stream:
        return stream.read(maximum + 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("schema", type=Path)
    parser.add_argument("holdout", type=Path)
    for name in ("source", "schema", "holdout"):
        parser.add_argument("--" + name + "-reviewed-sha256", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--tables", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        tables = args.tables.split(",")
        if len(set(tables)) != len(tables):
            raise ExportDenied("duplicate_allowed_table")
        artifacts = prepare(
            bounded(args.source, MAX_BYTES),
            bounded(args.schema, 65536),
            bounded(args.holdout, HOLDOUT_BYTES),
            source_sha256=args.source_reviewed_sha256,
            schema_sha256=args.schema_reviewed_sha256,
            holdout_sha256=args.holdout_reviewed_sha256,
            dataset=args.dataset,
            allowed_tables=frozenset(tables),
        )
        if args.output is not None:
            write(artifacts, args.output)
        manifest = json.loads(artifacts.manifest)
        print(
            json.dumps(
                {
                    "status": "prepared",
                    "written": args.output is not None,
                    "training_cases": manifest["training_cases"],
                    "validation_cases": manifest["validation_cases"],
                    "training_sha256": digest(artifacts.training),
                    "validation_sha256": digest(artifacts.validation),
                    "manifest_sha256": digest(artifacts.manifest),
                    "training_performed": False,
                    "network_calls": 0,
                    "database_calls": 0,
                }
            )
        )
        return 0
    except (ExportDenied, OSError, ValueError, TypeError, RecursionError):
        print(json.dumps({"status": "denied", "category": "sft_export_invalid"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
