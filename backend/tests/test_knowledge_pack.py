"""Prepared examples need exact review binding, a train split and closed SQL scope."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pytest
from eval.knowledge_pack import PackDenied, allowlist_hash, compile_pack

TABLES = frozenset({"account", "loan"})
PACK = {
    "schemaVersion": 1,
    "approved": True,
    "dataset": "synthetic-bank",
    "allowlist_sha256": allowlist_hash(TABLES),
    "examples": [
        {
            "id": "account_count",
            "split": "train",
            "question": "How many accounts?",
            "sql": "SELECT COUNT(*) FROM account",
            "tables": ["account"],
        }
    ],
}


def compile(value, **kwargs):
    raw = json.dumps(value).encode()
    return compile_pack(
        raw,
        reviewed_sha256=kwargs.pop("reviewed_sha256", hashlib.sha256(raw).hexdigest()),
        dataset=kwargs.pop("dataset", "synthetic-bank"),
        allowed_tables=TABLES,
        **kwargs,
    )


def test_reviewed_pack_compiles_to_the_existing_training_jsonl_contract():
    result = compile(PACK)
    assert json.loads(result) == PACK["examples"][0]
    assert result.endswith(b"\n")


@pytest.mark.parametrize(
    "attack",
    [
        "unreviewed",
        "review_mismatch",
        "dataset",
        "allowlist",
        "test_split",
        "duplicate_id",
        "duplicate_question",
        "unknown_field",
        "write_sql",
        "foreign_table",
        "undeclared_table",
        "unused_table",
        "too_many",
        "oversized",
        "not_bool",
    ],
)
def test_pack_promotion_fails_closed(attack):
    value = copy.deepcopy(PACK)
    options = {}
    example = value["examples"][0]
    if attack == "unreviewed":
        value["approved"] = False
    elif attack == "review_mismatch":
        options["reviewed_sha256"] = "0" * 64
    elif attack == "dataset":
        options["dataset"] = "other-dataset"
    elif attack == "allowlist":
        value["allowlist_sha256"] = "0" * 64
    elif attack == "test_split":
        example["split"] = "test"
    elif attack == "duplicate_id":
        value["examples"].append(copy.deepcopy(example))
    elif attack == "duplicate_question":
        other = copy.deepcopy(example)
        other["id"] = "other"
        other["question"] = " HOW MANY ACCOUNTS? "
        value["examples"].append(other)
    elif attack == "unknown_field":
        value["run_automatically"] = True
    elif attack == "write_sql":
        example["sql"] = "DELETE FROM account"
    elif attack == "foreign_table":
        example.update(sql="SELECT * FROM private_payroll", tables=["private_payroll"])
    elif attack == "undeclared_table":
        example["sql"] = "SELECT * FROM loan"
    elif attack == "unused_table":
        example["tables"].append("loan")
    elif attack == "too_many":
        value["examples"] *= 65
    elif attack == "oversized":
        example["sql"] = "x" * 17000
    elif attack == "not_bool":
        value["approved"] = 1
    with pytest.raises(PackDenied) as failure:
        compile(value, **options)
    assert "private_payroll" not in str(failure.value)


def test_ambiguous_json_never_receives_last_wins_review_semantics():
    raw = b'{"approved":false,"approved":true}'
    with pytest.raises(PackDenied):
        compile_pack(
            raw,
            reviewed_sha256=hashlib.sha256(raw).hexdigest(),
            dataset="synthetic-bank",
            allowed_tables=TABLES,
        )


def test_cli_defaults_to_a_count_only_dry_run(tmp_path):
    path = tmp_path / "input.json"
    raw = json.dumps(PACK).encode()
    path.write_bytes(raw)
    args = [
        sys.executable,
        "-m",
        "eval.knowledge_pack",
        str(path),
        "--reviewed-sha256",
        hashlib.sha256(raw).hexdigest(),
        "--dataset",
        "synthetic-bank",
        "--tables",
        "account,loan",
    ]
    result = subprocess.run(
        args,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        check=True,
        timeout=5,
    )
    report = json.loads(result.stdout)
    assert (
        report["written"] is False
        and report["network_calls"] == report["database_writes"] == 0
    )
    assert b"How many accounts" not in result.stdout and b"SELECT" not in result.stdout
    assert list(tmp_path.iterdir()) == [path]


def test_cli_cannot_overwrite_an_existing_operator_artifact(tmp_path):
    path = tmp_path / "input.json"
    raw = json.dumps(PACK).encode()
    path.write_bytes(raw)
    output = tmp_path / "prepared.jsonl"
    output.write_text("retain this artifact")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval.knowledge_pack",
            str(path),
            "--reviewed-sha256",
            hashlib.sha256(raw).hexdigest(),
            "--dataset",
            "synthetic-bank",
            "--tables",
            "account,loan",
            "--output",
            str(output),
        ],
        capture_output=True,
        cwd=Path(__file__).resolve().parents[2],
        timeout=5,
    )
    assert (
        result.returncode == 1
        and json.loads(result.stdout)["category"] == "file_unavailable"
    )
    assert output.read_text() == "retain this artifact"
