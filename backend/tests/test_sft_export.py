"""SFT export remains reviewed, split-isolated, bounded and entirely offline."""

import copy
import json
import time
from pathlib import Path

import pytest

from eval import sft_export
from eval.knowledge_pack import allowlist_hash
from eval.sft_contract import ExportDenied, digest
from nl2sql.control import Budget, CURRENT
from nl2sql.generate import SYSTEM_INSTRUCTION

SCHEMA = b"CREATE TABLE account(account_id integer);\nCREATE TABLE loan(loan_id integer, amount numeric);"
TABLES = frozenset({"account", "loan"})
SOURCE = {
    "schemaVersion": 1,
    "approved": True,
    "dataset": "synthetic-bank-sft",
    "allowlist_sha256": allowlist_hash(TABLES),
    "schema_sha256": digest(SCHEMA),
    "provenance": {
        "source_id": "aqua-synthetic-review-fixture",
        "revision": "fixture-v1",
        "rights": "aqua_owned",
        "license": "LicenseRef-AquaOwned",
        "reviewed_for_sft": True,
        "aqua_or_public_only": True,
        "no_company_data": True,
        "semantic_leakage_reviewed": True,
    },
    "examples": [
        {
            "id": "account_count",
            "split": "train",
            "question": "How many accounts?",
            "sql": "SELECT COUNT(*) FROM account",
            "tables": ["account"],
        },
        {
            "id": "loan_average",
            "split": "validation",
            "question": "Average loan amount?",
            "sql": "SELECT AVG(amount) FROM loan",
            "tables": ["loan"],
        },
    ],
}
HOLDOUT = {
    "id": "heldout_loan_max",
    "split": "test",
    "question": "Largest loan identifier?",
    "sql": "SELECT MAX(loan_id) FROM loan",
}


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode()


def prepare(source=None, schema=SCHEMA, holdout=None, **overrides):
    raw, test = encode(SOURCE if source is None else source), encode(
        HOLDOUT if holdout is None else holdout
    )
    arguments = {
        "source_sha256": digest(raw),
        "schema_sha256": digest(schema),
        "holdout_sha256": digest(test),
        "dataset": SOURCE["dataset"],
        "allowed_tables": TABLES,
    } | overrides
    return sft_export.prepare(raw, schema, test, **arguments)


def test_export_uses_production_messages_and_clears_ambient_private_history():
    parent = Budget(
        time.monotonic() + 120,
        lambda name: None,
        context=[{"question": "PRIVATE_AMBIENT_CANARY", "sql": "PRIVATE_SQL_CANARY"}],
    )
    token = CURRENT.set(parent)
    try:
        artifacts = prepare()
        assert CURRENT.get() is parent
    finally:
        CURRENT.reset(token)
    training, validation = json.loads(artifacts.training), json.loads(
        artifacts.validation
    )
    assert training["messages"][0] == {"role": "system", "content": SYSTEM_INSTRUCTION}
    assert training["messages"][1]["role"] == "user"
    assert json.loads(training["messages"][2]["content"]) == {
        "sql": SOURCE["examples"][0]["sql"]
    }
    assert "heldout_loan_max" not in artifacts.training.decode()
    assert "PRIVATE_" not in (artifacts.training + artifacts.validation).decode()
    assert validation["messages"][2]["role"] == "assistant"
    manifest = json.loads(artifacts.manifest)
    assert manifest["source_reviewed_sha256"] == digest(encode(SOURCE))
    assert all(
        value != manifest["source_reviewed_sha256"]
        for value in manifest["converted_compiler_input_sha256"].values()
    )
    assert not manifest["declarations_attested"] and not manifest["training_performed"]
    assert (
        not manifest["adequate_training_corpus_claimed"] and not manifest["tokenized"]
    )
    assert not manifest["model"]["enable_thinking"]
    assert manifest["model"]["revision"] == "1cfa9a7208912126459214e8b04321603b3df60c"
    assert manifest["training_sha256"] == digest(artifacts.training)
    assert SOURCE["examples"][0]["question"] not in artifacts.manifest.decode()


@pytest.mark.parametrize(
    "attack",
    [
        "source_review",
        "schema_review",
        "holdout_review",
        "unreviewed",
        "rights",
        "company",
        "semantic",
        "unknown",
        "schema_scope",
        "dataset_scope",
        "write",
        "foreign",
        "test_promotion",
        "missing_validation",
        "oversize",
        "too_many",
    ],
)
def test_review_rights_scope_and_size_gates_fail_closed(attack):
    value, options = copy.deepcopy(SOURCE), {}
    if attack.endswith("_review"):
        options[attack.replace("_review", "_sha256")] = "0" * 64
    elif attack == "unreviewed":
        value["approved"] = False
    elif attack == "rights":
        value["provenance"]["rights"] = "company_internal"
    elif attack == "company":
        value["provenance"]["no_company_data"] = False
    elif attack == "semantic":
        value["provenance"]["semantic_leakage_reviewed"] = False
    elif attack == "unknown":
        value["auto_train"] = True
    elif attack == "schema_scope":
        value["schema_sha256"] = "0" * 64
    elif attack == "dataset_scope":
        value["dataset"] = "foreign"
    elif attack == "write":
        value["examples"][0]["sql"] = "DELETE FROM account"
    elif attack == "foreign":
        value["examples"][0].update(
            sql="SELECT COUNT(*) FROM private_company", tables=["private_company"]
        )
    elif attack == "test_promotion":
        value["examples"][1]["split"] = "test"
    elif attack == "missing_validation":
        value["examples"][1]["split"] = "train"
    elif attack == "oversize":
        value["examples"][0]["question"] = "x" * 262145
    else:
        value["examples"] *= 33
    with pytest.raises(ExportDenied):
        prepare(value, **options)


@pytest.mark.parametrize("where", ["partitions", "holdout"])
@pytest.mark.parametrize("collision", ["id", "normalized_question", "canonical_sql"])
def test_duplicates_and_independent_holdout_leakage_are_rejected(where, collision):
    value, heldout = copy.deepcopy(SOURCE), copy.deepcopy(HOLDOUT)
    target = value["examples"][1] if where == "partitions" else heldout
    if collision == "id":
        target["id"] = value["examples"][0]["id"]
    elif collision == "normalized_question":
        target["question"] = "  Ｈｏｗ many ACCOUNTS!!!  "
    else:
        target["sql"] = "/* formatting differs */ select count(*) from account"
        if where == "partitions":
            target["tables"] = ["account"]
    with pytest.raises(ExportDenied, match="duplicate_or_holdout_leakage"):
        prepare(value, holdout=heldout)


def test_non_test_holdout_is_never_promoted_into_either_partition():
    with pytest.raises(ExportDenied, match="test_only_holdout"):
        prepare(holdout=HOLDOUT | {"split": "train"})


def test_equivalent_protected_records_keep_both_ids_and_still_exclude_training():
    from eval.sft_contract import exclude_holdout

    protected = [
        HOLDOUT
        | {
            "id": "t12",
            "question": "What is the highest replacement cost of any film?",
            "sql": "SELECT max(replacement_cost) FROM film",
        },
        HOLDOUT
        | {
            "id": "z14",
            "question": "What is the highest replacement cost?",
            "sql": "/* same protected SQL */ select max(replacement_cost) from film",
            "rule": "single",
        },
    ]
    raw = b"\n".join(encode(c) for c in protected)
    tables = TABLES | {"film"}
    assert exclude_holdout(SOURCE["examples"], raw, digest(raw), tables) == 2
    for field, value in (
        ("id", "z14"),
        ("question", "What is the highest replacement cost?"),
        ("sql", "SELECT MAX(replacement_cost) FROM film"),
    ):
        examples = copy.deepcopy(SOURCE["examples"])
        examples[0][field] = value
        with pytest.raises(ExportDenied, match="duplicate_or_holdout_leakage"):
            exclude_holdout(examples, raw, digest(raw), tables)


def test_duplicate_protected_ids_and_unbounded_rule_metadata_are_denied():
    from eval.sft_contract import exclude_holdout

    duplicate = b"\n".join((encode(HOLDOUT), encode(HOLDOUT)))
    with pytest.raises(ExportDenied, match="holdout_invalid"):
        exclude_holdout(SOURCE["examples"], duplicate, digest(duplicate), TABLES)
    for rule in (True, "x" * 33, "not a closed identifier"):
        raw = encode(HOLDOUT | {"rule": rule})
        with pytest.raises(ExportDenied, match="holdout_rule_invalid"):
            exclude_holdout(SOURCE["examples"], raw, digest(raw), TABLES)


def test_create_only_export_and_partial_failure_manifest_boundary(
    tmp_path, monkeypatch
):
    artifacts = prepare()
    output = tmp_path / "private-export"
    sft_export.write(artifacts, output)
    original = (output / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        sft_export.write(artifacts, output)
    assert (output / "manifest.json").read_bytes() == original
    with pytest.raises(ExportDenied, match="outside_application"):
        sft_export.write(artifacts, sft_export.ROOT / "never-write-sft-here")
    real_open = sft_export.os.open

    def fail_validation(path, flags, mode):
        if Path(path).name == "validation.jsonl":
            raise OSError("synthetic output failure")
        return real_open(path, flags, mode)

    monkeypatch.setattr(sft_export.os, "open", fail_validation)
    incomplete = tmp_path / "incomplete"
    with pytest.raises(OSError):
        sft_export.write(artifacts, incomplete)
    assert (incomplete / "train.jsonl").exists()
    assert not (incomplete / "manifest.json").exists()


def test_cli_defaults_to_counts_and_hashes_without_writing(tmp_path, capsys):
    files = [
        tmp_path / name for name in ("reviewed.json", "schema.sql", "holdout.jsonl")
    ]
    payloads = [encode(SOURCE), SCHEMA, encode(HOLDOUT)]
    for path, raw in zip(files, payloads):
        path.write_bytes(raw)
    args = [
        *(str(p) for p in files),
        "--source-reviewed-sha256",
        digest(payloads[0]),
        "--schema-reviewed-sha256",
        digest(payloads[1]),
        "--holdout-reviewed-sha256",
        digest(payloads[2]),
        "--dataset",
        SOURCE["dataset"],
        "--tables",
        "account,loan",
    ]
    assert sft_export.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert (
        result["written"] is False
        and result["training_cases"] == result["validation_cases"] == 1
    )
    assert result["network_calls"] == result["database_calls"] == 0
    assert len(list(tmp_path.iterdir())) == 3
    assert SOURCE["examples"][0]["question"] not in json.dumps(result)
