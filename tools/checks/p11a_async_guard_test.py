"""Compile the actual async DSN tripwires with a fake driver; no I/O or loop."""

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOCKET = "host=/run/aqua-app-db port=5432 dbname=aqua_app user=aqua_app_runtime password=fixture-only sslmode=disable"
RUNTIME = (
    "postgresql://aqua_app_runtime:fixture-only@127.0.0.1:5432/aqua_app?sslmode=disable"
)


def wrapper(path, *, fixture=True):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "asynchronous_database_connect"
    ]
    assert len(nodes) == 1
    calls = []

    async def driver(cls, dsn, **kwargs):
        calls.append((cls, dsn, kwargs))
        return "fake_connection"

    namespace = {
        "DSN": SOCKET,
        "asynchronous_database": driver,
        "original_asynchronous_database_connect": driver,
        "app_fixture": fixture,
        "Any": object,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace["asynchronous_database_connect"], calls, tree


def run_immediate(coroutine):
    # The fake driver has no await point. An unexpected real await is a failure.
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    finally:
        coroutine.close()
    raise AssertionError("offline tripwire attempted actual asynchronous I/O")


class AsyncGuardTests(unittest.TestCase):
    def test_browser_runtime_only_and_no_override_reaches_driver(self):
        checked, calls, _ = wrapper("tools/checks/p05_browser_worker.py")
        self.assertEqual(
            run_immediate(
                checked(
                    object,
                    SOCKET,
                    autocommit=True,
                    connect_timeout=2,
                    prepare_threshold=None,
                )
            ),
            "fake_connection",
        )
        for dsn, kwargs in [
            (SOCKET.replace("runtime", "migrator"), {}),
            (SOCKET + " options=-csearch_path=public", {}),
            ("postgresql://example.invalid/aqua_app", {}),
            (SOCKET, {"host": "example.invalid"}),
            (SOCKET, {"service": "developer"}),
            (SOCKET, {"autocommit": False}),
            (SOCKET, {"connect_timeout": 3}),
            (SOCKET, {"prepare_threshold": 1}),
        ]:
            with (
                self.subTest(dsn=dsn, kwargs=kwargs),
                self.assertRaises(AssertionError),
            ):
                run_immediate(checked(object, dsn, **kwargs))
        self.assertEqual(len(calls), 1)

    def test_backend_runtime_only_and_no_fixture_denies(self):
        checked, calls, _ = wrapper("backend/tests/safety.py")
        self.assertEqual(
            run_immediate(
                checked(
                    object,
                    RUNTIME,
                    autocommit=True,
                    connect_timeout=2,
                    prepare_threshold=None,
                )
            ),
            "fake_connection",
        )
        for dsn, kwargs in [
            (RUNTIME.replace("runtime", "migrator"), {}),
            (RUNTIME.replace("runtime", "backup"), {}),
            ("postgresql://example.invalid/aqua_app", {}),
            (RUNTIME, {"options": "-c role=other"}),
            (RUNTIME, {"autocommit": False}),
            (RUNTIME, {"connect_timeout": 3}),
            (RUNTIME, {"row_factory": object()}),
        ]:
            with (
                self.subTest(dsn=dsn, kwargs=kwargs),
                self.assertRaises(AssertionError),
            ):
                run_immediate(checked(object, dsn, **kwargs))
        self.assertEqual(len(calls), 1)
        unconfigured, denied_calls, _ = wrapper(
            "backend/tests/safety.py", fixture=False
        )
        with self.assertRaises(AssertionError):
            run_immediate(unconfigured(object, RUNTIME))
        self.assertEqual(denied_calls, [])

    def test_both_installations_replace_the_actual_async_driver_entry(self):
        for path in ("tools/checks/p05_browser_worker.py", "backend/tests/safety.py"):
            _, _, tree = wrapper(path)
            assignments = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "classmethod"
                and len(node.value.args) == 1
                and isinstance(node.value.args[0], ast.Name)
                and node.value.args[0].id == "asynchronous_database_connect"
            ]
            self.assertEqual(len(assignments), 1)
            self.assertEqual(
                ast.unparse(assignments[0].targets[0]),
                "psycopg.AsyncConnection.connect",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
