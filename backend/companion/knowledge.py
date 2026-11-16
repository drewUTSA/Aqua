"""A bounded, reviewed Aqua help snapshot; content cannot choose an action."""

from dataclasses import dataclass
import hashlib
import re
from collections.abc import Callable

from companion.data_contract import CompanionDenied, _identifier, _load, _text
from nl2sql.retrieval.hybrid import tokens

MAX_PACK_BYTES = 16384
FIELDS = {"id", "topic", "title", "terms", "text", "status", "reviewed", "supersedes"}
TOPICS = {"overview", "questions", "results", "privacy"}


@dataclass(frozen=True)
class HelpRecord:
    id: str
    topic: str
    title: str
    terms: frozenset[str]
    text: str


@dataclass(frozen=True)
class Knowledge:
    revision: str
    records: tuple[HelpRecord, ...]


def load_pack(raw: bytes, *, reviewed_sha256: str) -> Knowledge:
    """Bind reviewed bytes; a supplied digest is not proof of authorization."""
    if (
        type(raw) is not bytes
        or len(raw) > MAX_PACK_BYTES
        or type(reviewed_sha256) is not str
        or re.fullmatch(r"[a-f0-9]{64}", reviewed_sha256) is None
        or hashlib.sha256(raw).hexdigest() != reviewed_sha256
    ):
        raise CompanionDenied("help_review_binding_invalid")
    pack = _load(raw)
    if (
        type(pack) is not dict
        or set(pack) != {"schemaVersion", "records"}
        or type(pack["schemaVersion"]) is not int
        or pack["schemaVersion"] != 1
        or type(pack["records"]) is not list
        or not 1 <= len(pack["records"]) <= 16
    ):
        raise CompanionDenied("help_pack_invalid")
    records, active = {}, []
    for item in pack["records"]:
        if (
            type(item) is not dict
            or set(item) != FIELDS
            or not _identifier(item["id"])
            or item["id"] in records
            or type(item["topic"]) is not str
            or item["topic"] not in TOPICS
            or not _text(item["title"], 120)
            or not _text(item["text"], 2048)
            or type(item["reviewed"]) is not bool
            or type(item["status"]) is not str
            or item["status"] not in {"active", "proposed", "superseded", "rejected"}
        ):
            raise CompanionDenied("help_record_invalid")
        terms, prior = item["terms"], item["supersedes"]
        if (
            type(terms) is not list
            or not 1 <= len(terms) <= 16
            or not all(
                type(t) is str and re.fullmatch(r"[a-z][a-z0-9]{0,31}", t)
                for t in terms
            )
            or len(set(terms)) != len(terms)
            or type(prior) is not list
            or len(prior) > 16
            or not all(_identifier(key) for key in prior)
            or len(set(prior)) != len(prior)
            or item["id"] in prior
        ):
            raise CompanionDenied("help_record_invalid")
        records[item["id"]] = item
        if item["status"] == "active" and item["reviewed"] is True:
            active.append(
                HelpRecord(
                    item["id"],
                    item["topic"],
                    item["title"],
                    frozenset(word for term in terms for word in tokens(term)),
                    item["text"],
                )
            )
    # Supersession must resolve to a retained historical record, never a live one.
    for item in records.values():
        for key in item["supersedes"]:
            if key not in records or records[key]["status"] != "superseded":
                raise CompanionDenied("help_lifecycle_invalid")
    for item in records.values():
        seen, pending = set(), list(item["supersedes"])
        while pending:
            key = pending.pop()
            if key == item["id"]:
                raise CompanionDenied("help_lifecycle_invalid")
            if key not in seen:
                seen.add(key)
                pending.extend(records[key]["supersedes"])
    if not active:
        raise CompanionDenied("help_no_reviewed_sources")
    return Knowledge(reviewed_sha256, tuple(active))


def lookup(
    pack: Knowledge, question: str, *, check: Callable[[], None]
) -> HelpRecord | None:
    """A tied or absent match abstains; this score is not model confidence."""
    query = set(tokens(question))
    scored = []
    for record in pack.records:
        check()
        score = len(query & record.terms)
        if score:
            scored.append((score, record))
    check()
    scored.sort(key=lambda value: (-value[0], value[1].id))
    if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None
    return scored[0][1]
