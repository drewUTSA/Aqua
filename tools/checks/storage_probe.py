"""Network-isolated installer fixture; synthetic credentials only."""

import os
import psycopg
from storage.config import load_storage_settings
from storage.pool import Storage

os.environ["APP_STORAGE_ENABLED"] = "true"
storage = Storage(load_storage_settings())
try:
    storage.open()
    assert storage.readiness()["schema_version"] == 8
    with storage.transaction() as conn:
        assert conn.execute("SHOW listen_addresses").fetchone() == ("",)
    try:
        with storage.transaction() as conn:
            conn.execute("CREATE TABLE app.denied_fixture(id int)")
    except Exception as error:
        assert str(error) == "application_storage_unavailable"
    else:
        raise AssertionError("runtime DDL was allowed")
    assert storage.readiness()["status"] == "ready"
    bad = os.environ["APP_DATABASE_URL"].replace("aqua_app_runtime:", "aqua_app_owner:")
    try:
        psycopg.connect(bad, connect_timeout=2)
    except psycopg.Error:
        pass
    else:
        raise AssertionError("nonlogin owner connected")
    from psycopg.conninfo import conninfo_to_dict

    bad = conninfo_to_dict(os.environ["APP_DATABASE_URL"])
    bad["password"] = "incorrect-fixture-password"
    try:
        psycopg.connect(**bad, connect_timeout=2)
    except psycopg.Error:
        pass
    else:
        raise AssertionError("incorrect password accepted")
finally:
    storage.close()
print("isolated_runtime_ready_and_ddl_denied")
