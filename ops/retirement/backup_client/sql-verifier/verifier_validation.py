"""Keyless full authority comparison against trusted signed bytes and source SQL."""

import hashlib
import json

from retirement.checkpoint import RECORD_BYTES, decode
from verifier_checks import helpers
from verifier_process import Failure

TABLES = ("control", "owners", "intents", "pages", "fingerprints", "journal")
OWNER_FLOORS = """SELECT count(*) FROM retirement.owners o FULL JOIN
 (SELECT owner_id,max(history_floor) h,max(privacy_floor) p,max(auth_floor) a,bool_or(account_closed) c FROM retirement.intents GROUP BY owner_id) i USING(owner_id)
 WHERE o.owner_id IS NULL OR i.owner_id IS NULL OR (o.history_floor,o.privacy_floor,o.auth_floor,o.account_closed) IS DISTINCT FROM (i.h,i.p,i.a,i.c)"""
FINGERPRINTS = """WITH encoded AS (
 SELECT convert_from(substring(e.item FROM 2 FOR 64),'UTF8') dataset_key,encode(substring(e.item FROM 66 FOR 16),'hex')::uuid key_id,get_byte(e.item,81)::smallint kind,substring(e.item FROM 83 FOR 32) digest,p.intent_id
 FROM retirement.pages p CROSS JOIN LATERAL unnest(p.entries) e(item)), original AS (
 SELECT DISTINCT dataset_key,key_id,kind,digest FROM encoded)
 SELECT count(*) FROM original o FULL JOIN retirement.fingerprints f USING(dataset_key,key_id,kind,digest)
 WHERE o.dataset_key IS NULL OR f.first_intent IS NULL OR NOT EXISTS (
  SELECT 1 FROM encoded e WHERE (e.dataset_key,e.key_id,e.kind,e.digest,e.intent_id)=(f.dataset_key,f.key_id,f.kind,f.digest,f.first_intent))"""


def checked_chain(chain, expected):
    if (
        not isinstance(chain, bytes)
        or not 208 <= len(chain) <= 64 * 1024**2
        or len(chain) % RECORD_BYTES
        or hashlib.sha256(chain).hexdigest() != expected["protected_chain_sha256"]
        or chain[-208:].hex() != expected["head_hex"]
    ):
        raise Failure("verifier_trusted_chain_mismatch")
    previous, digests = None, []
    for index in range(len(chain) // RECORD_BYTES):
        head = decode(
            chain[index * RECORD_BYTES : (index + 1) * RECORD_BYTES],
            bytes.fromhex(expected["public_key"]),
            installation=expected["installation_id"],
            key_id=expected["identity_key_id"],
            commitment=bytes.fromhex(expected["key_commitment"]),
        )
        if (
            head.sequence != index
            or previous
            and head.previous_record != previous.record_digest
        ):
            raise Failure("verifier_signed_chain_link_invalid")
        previous = head
        digests.append(head.event_digest)
    return previous, digests


def denied(conn, query):
    import psycopg

    try:
        with conn.transaction():
            # Prove grants deny writes even when this session overrides its
            # default read-only setting; a25006 alone is not a privilege proof.
            conn.execute("SET TRANSACTION READ WRITE")
            conn.execute(query)
    except psycopg.Error as error:
        if error.sqlstate != "42501":
            raise Failure("verifier_privilege_denial_not_proven") from None
    else:
        raise Failure("verifier_unexpected_backup_privilege")


def privileges(conn):
    if conn.execute(
        "SELECT current_database(),current_user,session_user,rolsuper,rolinherit,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolconnlimit FROM pg_roles WHERE rolname=current_user"
    ).fetchone() != (
        "aqua_retirement",
        "aqua_retirement_backup",
        "aqua_retirement_backup",
        False,
        False,
        False,
        False,
        False,
        False,
        1,
    ):
        raise Failure("verifier_backup_role_invalid")
    for setting in (
        "default_transaction_read_only",
        "fsync",
        "full_page_writes",
        "synchronous_commit",
    ):
        if conn.execute("SHOW " + setting).fetchone() != ("on",):
            raise Failure("verifier_backup_durability_or_readonly_invalid")
    if conn.execute(
        "SELECT has_database_privilege(current_user,'aqua_app','CONNECT'),has_database_privilege(current_user,'aqua_retirement','TEMP'),has_schema_privilege(current_user,'retirement','CREATE'),(SELECT datconnlimit FROM pg_database WHERE datname='aqua_retirement')"
    ).fetchone() != (False, False, False, 4):
        raise Failure("verifier_backup_database_privileges_invalid")
    names = conn.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='retirement' AND c.relkind IN ('r','p') ORDER BY c.relname"
    ).fetchall()
    if [row[0] for row in names] != sorted(TABLES):
        raise Failure("verifier_six_table_inventory_invalid")
    for name in TABLES:
        qualified = "retirement." + name
        if conn.execute(
            "SELECT has_table_privilege(current_user,%s,'SELECT'),has_table_privilege(current_user,%s,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",
            (qualified, qualified),
        ).fetchone() != (True, False):
            raise Failure("verifier_backup_table_privileges_invalid")
    for statement in (
        "CREATE TABLE retirement.denied(x int)",
        "CREATE TEMP TABLE denied(x int)",
        "SET ROLE aqua_retirement_owner",
        "TRUNCATE retirement.control",
        "UPDATE retirement.control SET singleton=singleton",
        "DELETE FROM retirement.control WHERE false",
        "INSERT INTO retirement.control SELECT * FROM retirement.control WHERE false",
    ):
        denied(conn, statement)


def validate(conn, recovery, chain, expected, *, diagnostic=lambda _: None):
    """Only SELECT and existing source checker calls; never recover or grant users."""
    diagnostic("chain")
    head, signed_digests = checked_chain(chain, expected)
    diagnostic("privileges")
    privileges(conn)
    diagnostic("counts")
    counts = {
        name: conn.execute("SELECT count(*) FROM retirement." + name).fetchone()[0]
        for name in TABLES
    }
    if (
        counts["control"] != 1
        or counts["journal"] != head.sequence
        or counts["intents"] != head.sequence
        or counts["owners"] > 100000
        or counts["fingerprints"] > 250000
    ):
        raise Failure("verifier_full_dump_count_mismatch")
    diagnostic("control")
    columns = (
        "installation_id",
        "identity_key_id",
        "key_commitment",
        "next_sequence",
        "head_digest",
        "acknowledged_sequence",
        "acknowledged_digest",
        "intent_count",
        "owner_count",
        "fingerprint_count",
        "reserved_fingerprints",
        "pending_count",
        "logical_bytes",
    )
    row = conn.execute(
        "SELECT installation_id::text,identity_key_id::text,key_commitment,next_sequence,head_digest,acknowledged_sequence,acknowledged_digest,intent_count,owner_count,fingerprint_count,reserved_fingerprints,pending_count,logical_bytes FROM retirement.control"
    ).fetchone()
    control = dict(zip(columns, row, strict=True))
    pins = {
        "installation_id": expected["installation_id"],
        "identity_key_id": expected["identity_key_id"],
        "key_commitment": bytes.fromhex(expected["key_commitment"]),
        "next_sequence": head.sequence + 1,
        "head_digest": head.event_digest,
        "acknowledged_sequence": head.sequence,
        "acknowledged_digest": head.event_digest,
        "intent_count": counts["intents"],
        "owner_count": counts["owners"],
        "fingerprint_count": counts["fingerprints"],
        "reserved_fingerprints": 0,
        "pending_count": 0,
    }
    if any(control[name] != value for name, value in pins.items()):
        raise Failure("verifier_control_or_pending_state_invalid")
    diagnostic("events")
    checked_event, checked_pages = helpers()
    sequence, previous = 0, bytes(32)
    while True:
        diagnostic("events")
        rows = recovery.execute(
            "SELECT * FROM retirement.read_events(%s,128)", (sequence,)
        ).fetchall()
        if not rows:
            break
        if len(rows) > 128:
            raise Failure("verifier_event_batch_bound")
        for row in rows:
            record, state = checked_event(
                expected["installation_id"], row, previous, sequence + 1
            )
            sequence += 1
            if (
                state != "sealed"
                or sequence > head.sequence
                or record.event_digest != signed_digests[sequence]
            ):
                raise Failure("verifier_original_event_or_manifest_invalid")
            diagnostic("pages")
            checked_pages(recovery, record, expected["identity_key_id"])
            previous = record.event_digest
    diagnostic("events")
    if sequence != head.sequence or previous != head.event_digest:
        raise Failure("verifier_all_signed_events_not_covered")
    diagnostic("floors")
    if conn.execute(OWNER_FLOORS).fetchone() != (0,) or conn.execute(
        FINGERPRINTS
    ).fetchone() != (0,):
        raise Failure("verifier_original_floors_or_fingerprints_mismatch")
    diagnostic("accounting")
    if conn.execute(
        "SELECT coalesce(sum(512+expected_count::bigint*256),0),count(*) FILTER(WHERE state<>'sealed' OR received_count<>expected_count OR next_page<>expected_pages OR page_head<>expected_root) FROM retirement.intents"
    ).fetchone() != (control["logical_bytes"], 0):
        raise Failure("verifier_original_manifest_accounting_mismatch")
    result = {
        "authority_tables": sorted(TABLES),
        "original_pages_and_floors_verified": True,
        "events_verified": sequence,
        "table_counts": counts,
        "backup_role_select_only": True,
        "independent_database_cap": 4,
        "role_connection_cap": 1,
    }
    result["comparison_sha256"] = hashlib.sha256(
        json.dumps(result, sort_keys=True).encode()
    ).hexdigest()
    return result
