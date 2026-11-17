"""Original fictional US-bank snapshot; no database, network or private inputs."""

from datetime import date, datetime, timezone
from pathlib import Path
from types import MappingProxyType

from eval.banking.data import digest, encode, fields, identifier, load, require

AS_OF = "2026-11-16"
AS_OF_DATE = date.fromisoformat(AS_OF)
AS_OF_EPOCH = int(datetime(2026, 11, 16, tzinfo=timezone.utc).timestamp())
PERIOD = "2026-11"
CURRENCY = "USD"
DEMO_TENANT = "11111111-1111-4111-8111-111111111111"
SOURCE_VERSION = "aqua-synthetic-bank-v1"
EXPECTED_REVISION = "8c27aa965ae4087fc965f66957ab08dde9b18de1cf6abdd321102afb6f8cdd37"
BRANCHES = frozenset({"north", "central", "south"})
LEDGER_CATEGORIES = frozenset({"interest_income", "fee_income", "operating_expense"})
RECORD_FIELDS = {
    "deposit_buckets": {"id", "branch", "product", "accounts", "opening_cents"},
    "transactions": {
        "id",
        "date",
        "bucket_id",
        "direction",
        "rail",
        "amount_cents",
        "status",
    },
    "loans": {
        "id",
        "segment",
        "stage",
        "requested_cents",
        "outstanding_cents",
        "payment_cents",
        "review_due",
        "review_status",
    },
    "cases": {"id", "department", "status", "priority", "opened", "due", "related_id"},
    "treasury_assumptions": {"id", "kind", "amount_cents"},
    "reconciliation_observations": {"branch", "statement_closing_cents"},
    "controls": {"id", "department", "status", "due", "topic"},
    "training_cohorts": {"team", "course", "assigned", "completed", "due"},
    "vendors": {"id", "service", "risk", "review_due", "review_status"},
    "services": {"id", "vendor_id", "status", "incident_case_id"},
    "monthly_ledger": {"period", "category", "amount_cents", "complete"},
    "audit_issues": {"id", "related_id", "severity", "status", "due"},
}


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _validate(value):
    fields(
        value,
        set(RECORD_FIELDS)
        | {
            "schemaVersion",
            "bank_name",
            "tenant_id",
            "country",
            "currency",
            "period",
            "opening_date",
            "as_of",
            "synthetic",
            "source_version",
        },
    )
    require(
        type(value["schemaVersion"]) is int
        and value["schemaVersion"] == 1
        and value["bank_name"] == "Aqua Harbor Demo Bank"
        and value["tenant_id"] == DEMO_TENANT
        and value["country"] == "US"
        and value["currency"] == CURRENCY
        and value["period"] == PERIOD
        and value["opening_date"] == "2026-11-01"
        and value["as_of"] == AS_OF
        and value["synthetic"] is True
        and value["source_version"] == SOURCE_VERSION,
        "demo_fixture_identity",
    )
    identities = set()
    for name, expected in RECORD_FIELDS.items():
        rows = value[name]
        require(type(rows) is list and 1 <= len(rows) <= 64, "demo_fixture_budget")
        for row in rows:
            fields(row, expected, "demo_fixture_fields")
            for key, item in row.items():
                if key.endswith("_cents") or key in {
                    "accounts",
                    "assigned",
                    "completed",
                }:
                    require(
                        type(item) is int and 0 <= item <= 10**12, "demo_fixture_amount"
                    )
                elif key == "complete":
                    require(type(item) is bool, "demo_fixture_completeness")
                else:
                    require(type(item) is str and len(item) <= 64, "demo_fixture_text")
                if key in {"date", "opened", "due", "review_due"}:
                    observed = date.fromisoformat(item)
                    require(
                        date(2026, 1, 1) <= observed <= date(2026, 12, 31),
                        "demo_fixture_date",
                    )
                    if key in {"date", "opened"}:
                        require("2026-11-01" <= item <= AS_OF, "demo_fixture_snapshot")
            if "id" in row:
                require(
                    identifier(row["id"]) and row["id"] not in identities,
                    "demo_fixture_id",
                )
                identities.add(row["id"])
    buckets = {row["id"] for row in value["deposit_buckets"]}
    cases = {row["id"] for row in value["cases"]}
    vendors = {row["id"] for row in value["vendors"]}
    require(
        all(row["branch"] in BRANCHES for row in value["deposit_buckets"])
        and {row["branch"] for row in value["reconciliation_observations"]} == BRANCHES
        and all(
            row["bucket_id"] in buckets
            and row["direction"] in {"deposit", "withdrawal"}
            and row["status"] in {"posted", "exception"}
            for row in value["transactions"]
        )
        and all(
            row["related_id"] in identities
            for row in value["cases"] + value["audit_issues"]
        )
        and all(
            row["vendor_id"] in vendors
            and (not row["incident_case_id"] or row["incident_case_id"] in cases)
            for row in value["services"]
        )
        and all(
            row["completed"] <= row["assigned"] for row in value["training_cohorts"]
        ),
        "demo_fixture_reference",
    )
    ledger = value["monthly_ledger"]
    periods = [f"2025-{month:02d}" for month in range(5, 13)] + [
        f"2026-{month:02d}" for month in range(1, 12)
    ]
    expected_ledger = {
        (period, category) for period in periods for category in LEDGER_CATEGORIES
    }
    require(
        len(ledger) == len(expected_ledger)
        and {(row["period"], row["category"]) for row in ledger} == expected_ledger
        and all(row["complete"] is (row["period"] != PERIOD) for row in ledger),
        "demo_ledger_scope",
    )


def _load_fixture():
    path = Path(__file__).resolve().parent / "fixtures" / "bank.json"
    require(not path.is_symlink() and path.is_file(), "demo_fixture_path")
    with path.open("rb") as source:
        raw = source.read(32769)
    value = load(raw)
    _validate(value)
    require(digest(encode(value)) == EXPECTED_REVISION, "demo_fixture_revision")
    return _freeze(value)


DATA = _load_fixture()
SOURCE_REVISION = EXPECTED_REVISION
DATA_REVISION = SOURCE_REVISION


def fixture():
    """Return deeply immutable synthetic facts, never an arbitrary source path."""
    return DATA


def provenance():
    return {
        "bank_name": DATA["bank_name"],
        "synthetic": True,
        "source_origin": "Aqua-authored fictional fixture",
        "source_revision": SOURCE_REVISION,
        "source_version": SOURCE_VERSION,
        "as_of": AS_OF,
        "currency": CURRENCY,
        "jurisdiction": "US",
        "real_bank_data": False,
        "bank_authentication": False,
        "model_training_performed": False,
    }
