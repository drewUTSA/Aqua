"""Validate private storage independently from analytical and Google settings."""

from dataclasses import dataclass, field
import os
from collections.abc import Mapping

from psycopg.conninfo import conninfo_to_dict
import psycopg


class StorageConfigError(ValueError):
    """A fixed diagnostic must not contain the supplied DSN or password."""


@dataclass(frozen=True)
class StorageSettings:
    enabled: bool = False
    dsn: str = field(default="", repr=False)
    max_connections: int = 4
    max_waiting: int = 8
    wait_seconds: float = 2.0

    def __post_init__(self) -> None:
        valid = (
            1 <= self.max_connections <= 12
            and 1 <= self.max_waiting <= 32
            and 0.1 <= self.wait_seconds <= 5
        )
        if not valid:
            raise StorageConfigError("application_storage_limits_invalid")
        if self.enabled:
            validate_dsn(self.dsn, "aqua_app_runtime")


def validate_dsn(dsn: str, role: str) -> dict[str, str]:
    """Only the dedicated local app DB/role; service files/options cannot redirect."""
    try:
        values = conninfo_to_dict(dsn)
    except (psycopg.Error, ValueError, TypeError):
        raise StorageConfigError("application_storage_dsn_invalid") from None
    allowed = {"host", "port", "dbname", "user", "password", "sslmode"}
    if (
        not values
        or set(values) - allowed
        or values.get("dbname") != "aqua_app"
        or values.get("user") != role
        or values.get("host") not in {"127.0.0.1", "::1", "/run/aqua-app-db"}
        or values.get("port") not in {"5432", "55432"}
        or not values.get("password")
        or values.get("sslmode", "disable") != "disable"
    ):
        raise StorageConfigError("application_storage_dsn_invalid")
    return values


def load_storage_settings(environ: Mapping[str, str] | None = None) -> StorageSettings:
    """No dotenv, analytical URL fallback or implicit storage activation."""
    env = os.environ if environ is None else environ
    enabled = env.get("APP_STORAGE_ENABLED", "false").lower()
    if enabled not in {"true", "false"}:
        raise StorageConfigError("application_storage_flag_invalid")
    try:
        return StorageSettings(
            enabled == "true",
            env.get("APP_DATABASE_URL", ""),
            int(env.get("APP_DB_POOL_SIZE", "4")),
            int(env.get("APP_DB_MAX_WAITING", "8")),
            float(env.get("APP_DB_WAIT_SECONDS", "2")),
        )
    except (ValueError, TypeError):
        raise StorageConfigError("application_storage_configuration_invalid") from None
