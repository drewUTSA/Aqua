"""Initialize private synthetic app roles/DB inside the existing network-none PG."""

from pathlib import Path
from collections.abc import Callable


def initialize(docker: Callable, pg: str, root: Path) -> None:
    prefix = b"\\set migrator_password 'fixture-only'\n\\set runtime_password 'fixture-only'\n\\set backup_password 'fixture-only'\n"
    docker(
        "exec",
        "-i",
        pg,
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        data=prefix + (root / "backend/migrations/bootstrap.psql").read_bytes(),
    )
    docker(
        "exec",
        "-i",
        pg,
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        data=b"""
REVOKE CONNECT ON DATABASE aqua_test_bank, aqua_test_pagila FROM PUBLIC;
GRANT CONNECT ON DATABASE aqua_test_bank, aqua_test_pagila TO nl2sql_reader;
""",
    )
    hba = b"local all postgres peer\n"
    for role in ("aqua_app_runtime", "aqua_app_migrator", "aqua_app_backup"):
        hba += f"host aqua_app {role} 127.0.0.1/32 scram-sha-256\n".encode()
    hba += b"host aqua_app all 127.0.0.1/32 reject\n"
    hba += b"host aqua_test_bank nl2sql_reader 127.0.0.1/32 trust\n"
    hba += b"host aqua_test_pagila nl2sql_reader 127.0.0.1/32 trust\n"
    hba += b"host all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n"
    docker("exec", "-i", pg, "tee", "/var/lib/postgresql/data/pg_hba.conf", data=hba)
    docker("exec", pg, "psql", "-X", "-U", "postgres", "-c", "SELECT pg_reload_conf()")
