"""Secret-bearing HTTP/exception failures remain red with closed metadata only."""

import ast
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PROBE = load(
    "normal_runtime_probe",
    ROOT / "tools/checks/retirement_fixture/normal_runtime_probe.py",
)
load("ops.retirement.export_protocol", ROOT / "ops/retirement/export_protocol.py")
load("retirement_normal_protocol", ROOT / "tools/checks/retirement_normal_protocol.py")


@contextmanager
def child(raw, exit_code):
    stdout_read, stdout_write = os.pipe()
    stdin_read, stdin_write = os.pipe()
    os.write(stdout_write, raw)
    os.close(stdout_write)
    value = SimpleNamespace(
        stdout=os.fdopen(stdout_read, "rb", buffering=0),
        stdin=os.fdopen(stdin_write, "wb", buffering=0),
        wait=lambda timeout: exit_code,
    )
    try:
        yield value
    finally:
        value.stdout.close()
        value.stdin.close()
        os.close(stdin_read)


class FailureBoundary(unittest.TestCase):
    def test_secret_HTTP_failure_reports_closed_metadata_and_cannot_be_green(self):
        secret = "NEVER_PERSIST_SECRET_TOKEN"
        identifier = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        private_body = (secret + " unparseable HTML body").encode()
        connection = Mock()
        connection.getresponse.return_value = SimpleNamespace(
            status=503, read=lambda count: private_body
        )

        def failing_execute(value):
            PROBE._phase = "accepted_receipt"
            return PROBE.request(
                "POST",
                "/api/v1/me/data-deletions/by-intent/" + identifier,
                {"proof_token": secret},
                {"Cookie": secret},
            )

        with (
            patch.object(PROBE.sys, "argv", ["normal_runtime_probe.py", "--execute"]),
            patch.object(PROBE.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"{}"))),
            patch.object(PROBE, "execute", side_effect=failing_execute),
            patch.object(PROBE.http.client, "HTTPConnection", return_value=connection),
            redirect_stdout(io.StringIO()) as stdout,
            redirect_stderr(io.StringIO()) as stderr,
        ):
            with self.assertRaises(SystemExit) as stopped:
                PROBE.main()
            self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(stderr.getvalue(), "")
        raw = stdout.getvalue().encode()
        failure = json.loads(raw)
        diagnostic = PROBE.validate_failure(failure)
        self.assertEqual(
            diagnostic,
            {
                "phase": "accepted_receipt",
                "exception_class": "JSONDecodeError",
                "category": None,
                "http_failure": {
                    "route": "deletion_receipt",
                    "status": 503,
                    "bytes": len(private_body),
                    "body_sha256": hashlib.sha256(private_body).hexdigest(),
                },
            },
        )
        for private in (
            secret,
            identifier,
            "/api/",
            "Cookie",
            "proof_token",
            "unparseable HTML",
            "Traceback",
        ):
            self.assertNotIn(private, raw.decode())

        # Execute the actual host probe/finish functions without importing its
        # Docker runner. A failed child keeps the pre-existing nonzero assertion;
        # even a lying zero exit with a failure DTO cannot turn the gate green.
        source = (ROOT / "tools/checks/run_retirement_normal.py").read_text()
        selected = [
            ast.get_source_segment(source, node)
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name in {"probe", "finish"}
        ]
        namespace = {"io": io, "json": json, "time": time}
        exec(
            compile(
                "\n\n".join(selected), "/verified/normal_host_functions.py", "exec"
            ),
            namespace,
        )
        for exit_code, expected in (
            (1, "normal_fixture_child_exit_unconfirmed"),
            (0, "normal_fixture_failed_probe_reported_zero"),
        ):
            with self.subTest(child_exit=exit_code), child(raw, exit_code) as process:
                namespace["start"] = lambda *args: process
                public = {}
                resources = SimpleNamespace(remove=Mock(return_value=True))
                with self.assertRaisesRegex(RuntimeError, expected):
                    namespace["probe"](
                        resources,
                        "normal-purge",
                        {"receipt_token": secret},
                        [],
                        public_report=public,
                    )
                self.assertEqual(
                    public,
                    {
                        "probe_failure": {
                            "role": "normal-purge",
                            "diagnostic": diagnostic,
                        }
                    },
                )
                self.assertNotIn(secret, json.dumps(public))
        poisoned = {
            "status": "failed",
            "diagnostic": {**diagnostic, "raw_body": secret},
        }
        with self.assertRaises(RuntimeError):
            PROBE.validate_failure(poisoned)
        opaque_error = PROBE.failure(RuntimeError(secret))
        self.assertIsNone(opaque_error["diagnostic"]["category"])
        self.assertNotIn(secret, json.dumps(opaque_error))


if __name__ == "__main__":
    unittest.main()
