"""Trusted schema plus INSERT-only data restore; never execute dump schema as super."""

import hashlib
import re
import time

from verifier_process import Failure

PASSWORD = "q" * 43  # Public disposable fixture credential, never a real secret.
TABLES = ("control", "owners", "intents", "pages", "fingerprints", "journal")
CATALOG = b"""SELECT encode(sha256(convert_to(coalesce(string_agg(x,E'\\n' ORDER BY x),''),'UTF8')),'hex') FROM (
 SELECT 'F'||p.oid::regprocedure::text||pg_get_functiondef(p.oid) AS x FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='retirement'
 UNION ALL SELECT 'T'||c.relname||':'||r.rolname||':'||coalesce(c.relacl::text,'') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_roles r ON r.oid=c.relowner WHERE n.nspname='retirement'
 UNION ALL SELECT 'C'||conname||pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='retirement'
) all_catalog;"""


def sql(resources, raw, *, database="postgres", role="postgres"):
    args = ["exec", "-i"]
    if role != "postgres":
        args += ["--env=PGPASSWORD=" + PASSWORD]
    return resources.call(
        *args,
        resources.name + "-pg",
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        "/var/run/postgresql",
        "-U",
        role,
        "-d",
        database,
        "-At",
        data=raw,
    )


def initialize(resources, files, expected):
    resources.socket()
    pg = resources.create(
        "pg",
        [
            "postgres",
            "-c",
            "listen_addresses=",
            "-c",
            "unix_socket_directories=/var/run/postgresql,/run/aqua-app-db",
            "-c",
            "autovacuum_naptime=1s",
        ],
    )
    resources.call("start", pg)
    for _ in range(100):
        try:
            sql(resources, b"SELECT 1;")
            break
        except Failure:
            resources.budget.remaining()
            time.sleep(0.1)
    else:
        raise Failure("verifier_postgres_not_ready")
    sql(
        resources,
        b"CREATE DATABASE aqua_app; REVOKE ALL ON DATABASE aqua_app FROM PUBLIC;",
    )
    prefix = "".join(
        "\\set " + role + "_password '" + PASSWORD + "'\n"
        for role in ("writer", "recovery", "checkpoint")
    )
    sql(resources, prefix.encode() + files["sql/bootstrap.psql"])
    prefix = f"\\set installation_id '{expected['installation_id']}'\n\\set identity_key_id '{expected['identity_key_id']}'\n\\set key_commitment '{expected['key_commitment']}'\n"
    sql(resources, prefix.encode() + files["sql/schema.psql"])
    sql(
        resources,
        ("\\set backup_password '" + PASSWORD + "'\n").encode()
        + files["sql/backup.psql"],
    )
    tables = ",".join("retirement." + name for name in TABLES)
    sql(resources, ("TRUNCATE " + tables + ";").encode(), database="aqua_retirement")
    role = "aqua_retirement_restore"
    raw = f"CREATE ROLE {role} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1 PASSWORD '{PASSWORD}';GRANT CONNECT ON DATABASE aqua_retirement TO {role};ALTER ROLE {role} IN DATABASE aqua_retirement SET statement_timeout='30s';ALTER ROLE {role} IN DATABASE aqua_retirement SET lock_timeout='1s';"
    sql(resources, raw.encode())
    sql(
        resources,
        (
            f"GRANT USAGE ON SCHEMA retirement TO {role};GRANT INSERT ON "
            + tables
            + f" TO {role};"
        ).encode(),
        database="aqua_retirement",
    )
    hba = (
        "local all postgres peer\n"
        + "".join(
            f"local aqua_retirement aqua_retirement_{r} scram-sha-256\n"
            for r in ("writer", "recovery", "checkpoint", "backup", "restore")
        )
        + "local all all reject\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n"
    )
    resources.call(
        "exec",
        "-i",
        pg,
        "tee",
        "/var/lib/postgresql/data/pg_hba.conf",
        data=hba.encode(),
    )
    sql(resources, b"SELECT pg_reload_conf();")
    return sql(resources, CATALOG, database="aqua_retirement").strip()


def restore(resources, dump):
    if not 0 < len(dump) <= 128 * 1024**2 or not dump.startswith(b"PGDMP"):
        raise Failure("verifier_dump_bound_or_format_invalid")
    pg = resources.name + "-pg"
    listing = resources.call(
        "exec", "-i", pg, "pg_restore", "--list", data=dump, maximum=1048576
    )
    entries = [line for line in listing.splitlines() if b" TABLE DATA " in line]
    names = []
    for line in entries:
        match = re.fullmatch(
            rb"[0-9]+; [0-9]+ [0-9]+ TABLE DATA retirement ([a-z_]+) [^\r\n]+", line
        )
        if not match:
            raise Failure("verifier_unreviewed_data_entry")
        names.append(match[1].decode())
    if len(names) != 6 or set(names) != set(TABLES):
        raise Failure("verifier_complete_six_table_dump_required")
    # A full-schema dump may place data before its later FK declarations.
    # Our schema is trusted and its FKs are already active; select one exact
    # table at a time in source-defined parent-before-child order.
    for table in TABLES:
        resources.call(
            "exec",
            "-i",
            "--env=PGPASSWORD=" + PASSWORD,
            pg,
            "pg_restore",
            "--exit-on-error",
            "--data-only",
            "--no-owner",
            "--no-privileges",
            "--strict-names",
            "--schema=retirement",
            "--table=" + table,
            "-h",
            "/var/run/postgresql",
            "-U",
            "aqua_retirement_restore",
            "-d",
            "aqua_retirement",
            data=dump,
        )
    return hashlib.sha256(listing).hexdigest()
