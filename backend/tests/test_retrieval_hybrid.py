"""Metadata-only hybrid routing cannot widen the authorized retrieval context."""

from types import SimpleNamespace
import pytest
from nl2sql.errors import ContextDenied
from nl2sql.retrieval.hybrid import hybrid_tables, lexical, tokens
from nl2sql.schema import Column, Schema, Table


def schema(names=None):
    names = names or {
        "account": ("balance", "opened_at"),
        "loan": ("principal", "payment"),
        "customer": ("email",),
        "branch": ("city",),
        "transaction": ("amount",),
    }
    return Schema(
        {
            name: Table(
                name, tuple(Column(c, "text", False) for c in cols), (), frozenset()
            )
            for name, cols in names.items()
        }
    )


def test_exact_identifier_recovers_a_table_missed_by_semantic_top_four():
    visible = schema()
    result = hybrid_tables(
        visible, ["customer", "branch", "transaction", "loan"], "Show account balances"
    )
    assert "account" in result and len(result) == 4
    assert set(result) <= visible.allowed_tables


def test_semantic_lexical_agreement_ranks_first():
    assert (
        hybrid_tables(
            schema(), ["customer", "account", "loan", "branch"], "account balance"
        )[0]
        == "account"
    )


@pytest.mark.parametrize(
    "question", ["???", "显示统计", "please show all", "unmatchedword"]
)
def test_no_keyword_evidence_keeps_semantic_order(question):
    nearest = ["loan", "branch", "customer", "transaction"]
    assert hybrid_tables(schema(), nearest, question) == nearest


def test_unauthorized_vector_hit_still_denies_even_with_a_good_keyword_match():
    with pytest.raises(ContextDenied):
        hybrid_tables(schema(), ["account", "private_payroll"], "account balance")


def test_empty_vector_index_does_not_become_an_unverified_lexical_index():
    assert hybrid_tables(schema(), [], "account balance") == []


def test_values_comments_and_private_rows_do_not_enter_the_ranker():
    plain = schema()
    poisoned = Schema(
        {
            name: Table(
                t.name,
                tuple(
                    Column(c.name, c.type, False, ("SECRET_CANARY",), "SECRET_CANARY")
                    for c in t.columns
                ),
                (),
                frozenset(),
                "SECRET_CANARY",
            )
            for name, t in plain.tables.items()
        }
    )
    assert lexical(poisoned, "SECRET_CANARY") == []
    assert lexical(poisoned, "account balance") == lexical(plain, "account balance")


def test_separate_approved_schemas_cannot_inherit_each_others_candidates():
    first, second = schema({"account": ("balance",)}), schema({"film": ("title",)})
    assert hybrid_tables(first, ["account"], "balance") == ["account"]
    assert hybrid_tables(second, ["film"], "balance") == ["film"]
    with pytest.raises(ContextDenied):
        hybrid_tables(second, ["account"], "balance")


def test_duplicate_vector_hits_do_not_gain_extra_votes():
    assert hybrid_tables(
        schema(), ["loan", "loan", "account"], "balance"
    ) == hybrid_tables(schema(), ["loan", "account"], "balance")


@pytest.mark.parametrize("limit", [0, 9, -1])
def test_caller_cannot_expand_the_rank_budget(limit):
    with pytest.raises(ValueError):
        hybrid_tables(schema(), ["account"], "balance", limit)


def test_metadata_preparation_is_bounded_and_does_not_read_excess_columns():
    def columns():
        for _ in range(256):
            yield SimpleNamespace(name="amount")
        raise AssertionError("unbounded_column_scan")

    visible = SimpleNamespace(tables={"ledger": SimpleNamespace(columns=columns())})
    assert lexical(visible, "ledger") == ["ledger"]
    assert len(tokens("balance " * 10000)) <= 32


@pytest.mark.parametrize("enabled", [False, True])
def test_hybrid_selection_reuses_one_embedding_and_the_two_original_lookups(
    monkeypatch, enabled
):
    from nl2sql.config import Settings
    from nl2sql.retrieval import select

    inputs, lookups = [], []
    monkeypatch.setattr(
        select,
        "embed_query",
        lambda question, *args: inputs.append(question) or [0.0] * 768,
    )

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, args):
            lookups.append(query)
            if query == select._TABLES_SQL:
                return [
                    (name,) for name in ("customer", "loan", "branch", "transaction")
                ]
            return SimpleNamespace(fetchall=lambda: [])

    monkeypatch.setattr(select, "connect", lambda settings: Connection())
    context = select.VectorRetriever(Settings(retrieval_hybrid_enabled=enabled)).select(
        "Show account balances", schema()
    )
    assert len(inputs) == 1 and len(lookups) == 2
    assert ("account" in context.tables) is enabled


@pytest.mark.parametrize("value,expected", [("true", True), ("false", False)])
def test_typed_flag_survives_the_restricted_worker_payload(value, expected):
    from analysis.child_payload import payload
    from nl2sql.config import Settings, settings_from

    settings = settings_from({"RETRIEVAL_HYBRID_ENABLED": value})
    job = {
        "model": "ollama",
        "user_id": "synthetic",
        "grant_version": 1,
        "auth_epoch": 1,
        "context": [],
        "context_digest": b"0" * 32,
        "request_id": None,
    }
    sent = payload(job, "account balance", settings, 10)["settings"]
    assert Settings(**sent).retrieval_hybrid_enabled is expected
    assert "session_secret" not in sent and "indexer_database_url" not in sent


def test_invalid_hybrid_flag_cannot_silently_change_retrieval():
    from nl2sql.config import ConfigError, settings_from

    with pytest.raises(ConfigError, match="RETRIEVAL_HYBRID_ENABLED"):
        settings_from({"RETRIEVAL_HYBRID_ENABLED": "sometimes"})
