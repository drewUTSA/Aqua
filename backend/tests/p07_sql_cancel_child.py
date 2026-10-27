"""One fixed readonly sleep in the explicit detached PostgreSQL test namespace."""

import json
import os
from pathlib import Path
import re
import sys
import time

from analysis.child import contain, notify

contain(int(sys.argv[1]), float(sys.argv[2]) - time.monotonic())
raw = sys.stdin.buffer.readline(65537)
if len(raw) > 65536 or not raw.endswith(b"\n"):
    raise RuntimeError("sql_fixture_input_bound")
data = json.loads(raw)
dsn = data["settings"]["database_url"]
allowed = {
    f"postgresql://nl2sql_reader@127.0.0.1:5432/aqua_test_{name}": name
    for name in ("bank", "pagila")
}
if dsn not in allowed or not re.fullmatch(r"[a-f0-9]{32}", data["question"]):
    raise RuntimeError("sql_fixture_target_denied")
os.environ["AQUA_TEST_DATASET"] = allowed[dsn]
os.environ.pop("AQUA_TEST_APP_STORAGE", None)
sys.path.insert(0, str(Path(__file__).parent))
from safety import install  # noqa: E402 - explicit target guard precedes imports

install()
import psycopg  # noqa: E402 - no inherited service configuration is accepted

with psycopg.connect(dsn, connect_timeout=2) as conn:
    conn.read_only = True
    conn.execute("SET LOCAL statement_timeout = '10s'")
    conn.execute(
        "SELECT set_config('application_name',%s,false)",
        ("aqua-p07-sql-cancel-" + data["question"],),
    )
    notify("executing")
    conn.execute("SELECT pg_sleep(20)")
raise AssertionError("sql_fixture_was_not_cancelled")
