"""History used for follow-ups must preserve scope, order and bounded egress."""

from copy import deepcopy
import hashlib
import time

from analysis.context import encode, select
from analysis.policy import MAX_CONTEXT_BYTES
from workspace_fixtures import GOOD


def context(security, session, chat_id, sequence=1000):
    with security.storage.transaction() as conn:
        return select(
            conn,
            session.user["id"],
            chat_id,
            sequence,
            session.dataset_key,
            session.grant_version,
        )


def test_context_never_egresses_result_rows_assistant_text_or_foreign_history(security):
    _, owner = security.session()
    _, foreign = security.session("B")
    result = deepcopy(GOOD)
    result["message"] = "PRIVATE_ASSISTANT_SUMMARY_MUST_NOT_EGRESS"
    result["tables"][0]["rows"] = [{"value": "PRIVATE_RAW_ROW_MUST_NOT_EGRESS"}]
    saved = security.seed(owner, "Count authorized records", result=result)
    selected, digest = context(security, owner, saved["chat"]["id"])
    assert len(selected) == 1 and selected[0]["question"] == "Count authorized records"
    assert selected[0]["sql"] == GOOD["sql"]
    assert set(selected[0]) == {"message_id", "sequence", "question", "sql"}
    assert b"MUST_NOT_EGRESS" not in encode(selected)
    assert digest == hashlib.sha256(encode(selected)).digest()
    assert context(security, foreign, saved["chat"]["id"])[0] == []


def test_context_excludes_future_failed_other_dataset_and_previous_grant_turns(
    security,
):
    _, session = security.session()
    first = security.seed(session, "First approved question")
    chat = first["chat"]["id"]
    second = security.seed(session, "Future question", chat_id=chat)
    selected, _ = context(security, session, chat, second["input_message"]["sequence"])
    assert [row["question"] for row in selected] == ["First approved question"]
    with security.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.analysis_requests SET dataset_key='different-dataset' WHERE id=%s",
            (first["request"]["id"],),
        )
        conn.execute(
            "UPDATE app.analysis_requests SET grant_version=grant_version+1 WHERE id=%s",
            (second["request"]["id"],),
        )
    assert context(security, session, chat)[0] == []
    failed = {**GOOD, "status": "error", "sql": "UNVALIDATED_SQL_MUST_NOT_EGRESS"}
    security.seed(session, "Failed turn", chat_id=chat, result=failed)
    assert context(security, session, chat)[0] == []


def test_context_is_recent_ordered_bounded_and_semantically_fingerprinted(security):
    _, session = security.session()
    saved = security.seed(session, "Earlier 0")
    chat = saved["chat"]["id"]
    for number in range(1, 12):
        security.seed(session, f"Earlier {number}", chat_id=chat)
    selected, digest = context(security, session, chat)
    assert [item["question"] for item in selected] == [
        f"Earlier {n}" for n in range(4, 12)
    ]
    assert sum("sql" in item for item in selected) == 2
    assert len(encode(selected)) <= MAX_CONTEXT_BYTES
    other = security.seed(session, "A different conversation")
    assert context(security, session, other["chat"]["id"])[1] != digest
    assert hashlib.sha256(encode(list(reversed(selected)))).digest() != digest


def test_multibyte_history_budget_is_bytes_and_never_sends_whole_tables(security):
    _, session = security.session()
    saved = security.seed(session, "\u754c" * 2000)
    chat = saved["chat"]["id"]
    for _ in range(7):
        security.seed(session, "\u754c" * 2000, chat_id=chat)
    selected, _ = context(security, session, chat)
    assert selected and len(selected) < 8
    assert len(encode(selected)) <= MAX_CONTEXT_BYTES
    assert all(
        set(item) <= {"message_id", "sequence", "question", "sql"} for item in selected
    )


def test_identical_followup_text_cannot_reuse_other_context_principal_or_grant_cache():
    from nl2sql.cache import AnswerCache
    from nl2sql.config import Settings
    from nl2sql.control import Budget, CURRENT
    from nl2sql.pipeline import Answer
    from nl2sql.query_service import run
    from nl2sql.schema import Schema

    cache, called = AnswerCache(600), []
    settings = Settings(database_url="synthetic-security-cache", llm_provider="ollama")

    def answer(question, configured, schema, **kwargs):
        called.append(CURRENT.get().context_digest)
        return Answer(
            question=question,
            sql=f"SELECT {len(called)} AS value",
            columns=["value"],
            rows=[(len(called),)],
        )

    def ask(history, principal="owner-A", grant=1, epoch=0, expired=False):
        digest = hashlib.sha256(encode(history)).hexdigest()
        token = CURRENT.set(
            Budget(
                time.monotonic() + (-1 if expired else 10),
                lambda stage: None,
                history,
                digest,
            )
        )
        try:
            return run(
                "And just the top three?",
                "ollama",
                settings,
                principal,
                grant,
                epoch,
                cache=cache,
                schema_reader=lambda configured: Schema({}),
                answerer=answer,
                retriever_factory=lambda configured: None,
            )
        finally:
            CURRENT.reset(token)

    first = [{"question": "Rank customer revenue", "sql": "SELECT 1"}]
    second = [{"question": "Rank film rentals", "sql": "SELECT 2"}]
    one, status = ask(first)
    assert status == 200 and ask(first)[0] == one and len(called) == 1
    two, _ = ask(second)
    assert one["sql"] != two["sql"] and len(called) == 2
    ask(first, principal="owner-B")
    ask(first, grant=2)
    ask(first, epoch=1)
    assert len(called) == 5
    expired, status = ask(first, expired=True)
    assert status == 503 and expired["tables"] == [] and len(called) == 5
