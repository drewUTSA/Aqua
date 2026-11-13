"""New synthetic app/authority DBs and create-only native fixture directories."""

import io
import json
import tarfile

from app_fixture import initialize
import p05_browser_docker as commands
from p05_browser_resources import wait_for_postgres
from retirement_host_resources import private_directory


def directories(resources, source: bytes) -> None:
    private_directory(resources.root)
    for name in ("source", "authority", "backend", "mail"):
        private_directory(resources.root / name)
    with tarfile.open(fileobj=io.BytesIO(source), mode="r:") as archive:
        members = archive.getmembers()
        if any(
            not item.isfile()
            or item.name.startswith("/")
            or ".." in item.name.split("/")
            for item in members
        ):
            raise RuntimeError("native_fixture_source_archive_invalid")
        archive.extractall(resources.root / "source", filter="data")
    for name in ("checkpoints.bin", "poison.bin", "mail-worker.lock"):
        (resources.root / "backend" / name).touch(mode=0o600)
    from ops.accountmail.physical_lock import prepare

    prepare(resources.root / "mail")
    resources.seal_layout()


def database(resources, root) -> None:
    resources.socket()
    pg = resources.create("pg")
    commands.docker("start", pg, timeout=15)
    wait_for_postgres(pg)
    commands.docker(
        "exec",
        "-i",
        pg,
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        data=b"CREATE ROLE nl2sql_reader LOGIN; CREATE DATABASE aqua_test_bank; CREATE DATABASE aqua_test_pagila;",
        timeout=15,
    )
    initialize(commands.docker, pg, root)
    from retirement.fingerprints import IdentityKey
    from native_support import AUTH_PASSWORD, IDENTITY_BYTES, INSTALLATION, KEY_ID

    prefix = "".join(
        "\\set " + role + "_password '" + AUTH_PASSWORD + "'\n"
        for role in ("writer", "recovery", "checkpoint")
    )

    def sql(raw):
        return commands.docker(
            "exec",
            "-i",
            pg,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            data=raw,
            timeout=15,
        )

    sql(prefix.encode() + (root / "ops/retirement/bootstrap.psql").read_bytes())
    commitment = IdentityKey(KEY_ID, IDENTITY_BYTES).commitment.hex()
    prefix = f"\\set installation_id '{INSTALLATION}'\n\\set identity_key_id '{KEY_ID}'\n\\set key_commitment '{commitment}'\n"
    sql(prefix.encode() + (root / "ops/retirement/schema.psql").read_bytes())
    sql(
        ("\\set backup_password '" + AUTH_PASSWORD + "'\n").encode()
        + (root / "ops/retirement/backup.psql").read_bytes()
    )
    hba = b"local all postgres peer\n"
    for role in ("runtime", "migrator", "backup"):
        hba += f"local aqua_app aqua_app_{role} scram-sha-256\n".encode()
    for role in ("writer", "checkpoint", "recovery", "backup"):
        hba += f"local aqua_retirement aqua_retirement_{role} scram-sha-256\n".encode()
    hba += b"local all all reject\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n"
    commands.docker(
        "exec",
        "-i",
        pg,
        "tee",
        "/var/lib/postgresql/data/pg_hba.conf",
        data=hba,
        timeout=10,
    )
    sql(b"SELECT pg_reload_conf();")


def flag(resources, operation: str) -> None:
    if operation not in {"set", "clear"}:
        raise ValueError("native_fixture_flag_operation_invalid")
    if operation == "clear":
        resources.append_ready = False
    try:
        identifier = resources.create(operation)
        resources.verify_layout()
        commands.docker("start", "--attach", identifier, timeout=resources.timeout(15))
        result = commands.docker(
            "inspect",
            identifier,
            "--format={{.State.Running}} {{.State.ExitCode}}",
            timeout=resources.timeout(10),
        )
        if result.strip() != b"false 0":
            raise RuntimeError("native_fixture_append_flag_or_setter_exit_unconfirmed")
    finally:
        # create records ownership before the daemon call; even a lost create,
        # start or inspect response must resolve/remove that exact owned name.
        if operation in resources.attempted and not resources.remove(operation):
            raise RuntimeError("native_fixture_flag_container_cleanup_unconfirmed")
    resources.append_ready = operation == "set"


def running() -> list:
    identifiers = (
        commands.docker("ps", "--quiet", "--no-trunc", timeout=10).decode().split()
    )
    return states(identifiers)


def states(identifiers: list) -> list:
    result = []
    for identifier in identifiers:
        raw = commands.docker(
            "inspect",
            identifier,
            "--format={{json .Id}}\n{{json .Image}}\n{{json .State.StartedAt}}\n{{json .State.Running}}",
            timeout=10,
        )
        result.append([json.loads(field) for field in raw.splitlines()])
    return result
