"""Private synthetic DB only: roles, migration recovery and bounded pooled state."""

import os

import psycopg
import pytest

from storage.config import StorageSettings
from storage.migrate import apply
from storage.pool import Storage

RUNTIME = (
    "postgresql://aqua_app_runtime:fixture-only@127.0.0.1:5432/aqua_app?sslmode=disable"
)
MIGRATOR = RUNTIME.replace("aqua_app_runtime", "aqua_app_migrator")
BACKUP = RUNTIME.replace("aqua_app_runtime", "aqua_app_backup")
SETTINGS = StorageSettings(True, RUNTIME, 1, 1, 0.4)
CANARY = "PRIVATE_STORAGE_CANARY"


@pytest.fixture
def app_database():
    if os.environ.get("AQUA_TEST_APP_STORAGE") != "1":
        pytest.skip("use the isolated application-storage runner")
    with psycopg.connect(MIGRATOR, autocommit=True, connect_timeout=2) as conn:
        conn.execute("SET ROLE aqua_app_owner")
        conn.execute("DROP SCHEMA app CASCADE")
        conn.execute("CREATE SCHEMA app AUTHORIZATION aqua_app_owner")
        conn.execute("RESET ROLE")
        yield conn


@pytest.fixture
def storage(app_database):
    apply(app_database)
    service = Storage(SETTINGS)
    try:
        yield service
    finally:
        service.close()
