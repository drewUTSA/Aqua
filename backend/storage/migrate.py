"""Explicit, transactional checksum ledger; never called during web startup."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

import psycopg

from storage.config import validate_dsn

ROOT = Path(__file__).resolve().parent.parent / "migrations"


class MigrationError(RuntimeError):
    """Fixed messages only: database errors may contain private SQL values."""


@dataclass(frozen=True)
class Migration:
    version: int
    text: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.text.replace("\r\n", "\n").encode()).hexdigest()


def migrations() -> tuple[Migration, ...]:
    found = []
    for path in sorted(ROOT.glob("*.sql")):
        if not re.fullmatch(r"\d{4}_[a-z_]+\.sql", path.name) or path.is_symlink():
            raise MigrationError("migration_file_invalid")
        text = path.read_text(encoding="utf-8")
        if len(text.encode()) > 131072:
            raise MigrationError("migration_file_too_large")
        found.append(Migration(int(path.name[:4]), text))
    if not found or [m.version for m in found] != list(range(1, len(found) + 1)):
        raise MigrationError("migration_sequence_invalid")
    return tuple(found)


def apply(conn: psycopg.Connection, steps: tuple[Migration, ...] | None = None) -> int:
    steps = migrations() if steps is None else steps
    try:
        with conn.transaction():
            if conn.execute("SELECT current_database(), current_user").fetchone() != (
                "aqua_app",
                "aqua_app_migrator",
            ):
                raise MigrationError("migration_identity_invalid")
            conn.execute("SET LOCAL lock_timeout = '3s'")
            conn.execute("SET LOCAL statement_timeout = '10s'")
            conn.execute("SELECT pg_advisory_xact_lock(1095848257)")
            conn.execute("SET LOCAL ROLE aqua_app_owner")
            conn.execute("SET LOCAL search_path = pg_catalog, app")
            conn.execute("CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION aqua_app_owner")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS app.schema_migrations (version integer PRIMARY KEY CHECK (version > 0), checksum text NOT NULL CHECK (length(checksum)=64), applied_at timestamptz NOT NULL DEFAULT now())"
            )
            applied = dict(
                conn.execute("SELECT version, checksum FROM app.schema_migrations")
            )
            known = {step.version: step.checksum for step in steps}
            if any(
                known.get(version) != checksum for version, checksum in applied.items()
            ):
                raise MigrationError("migration_history_mismatch")
            if sorted(applied) != list(range(1, len(applied) + 1)):
                raise MigrationError("migration_history_gap")
            for step in steps:
                if step.version not in applied:
                    conn.execute(step.text)
                    conn.execute(
                        "INSERT INTO app.schema_migrations(version,checksum) VALUES (%s,%s)",
                        (step.version, step.checksum),
                    )
            conn.execute(
                "GRANT USAGE ON SCHEMA app TO aqua_app_runtime, aqua_app_backup"
            )
            conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA app TO aqua_app_backup")
            conn.execute("GRANT SELECT ON app.schema_migrations TO aqua_app_runtime")
            return steps[-1].version
    except psycopg.Error:
        raise MigrationError("migration_failed_rolled_back") from None


def main() -> None:
    import os

    dsn = os.environ.get("APP_MIGRATOR_DATABASE_URL", "")
    validate_dsn(dsn, "aqua_app_migrator")
    try:
        with psycopg.connect(dsn, connect_timeout=3, autocommit=True) as conn:
            version = apply(conn)
        print(f"application_schema_version={version}")
    except psycopg.Error:
        raise MigrationError("migration_connection_unavailable") from None


if __name__ == "__main__":
    main()
