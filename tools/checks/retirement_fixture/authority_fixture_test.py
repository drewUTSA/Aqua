"""Local guard tests; no Docker, DB, keys or application source mutation."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location(
    "private_authority_fixture", HERE / "authority_fixture.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class FixtureGuards(unittest.TestCase):
    def test_default_invocation_has_no_resource_action(self):
        result = subprocess.run(
            [sys.executable, "-E", "-s", "-B", str(HERE / "authority_fixture.py")],
            capture_output=True,
            timeout=3,
            check=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {"status": "prepared_only", "Docker_actions": 0, "live_DDL": False},
        )

    def test_exact_source_manifest_rejects_missing_changed_and_extra_helpers(self):
        with tempfile.TemporaryDirectory(prefix=".guard-fixture-", dir=HERE) as name:
            root = Path(name).resolve()
            self.assertEqual(root.parent, HERE.resolve())
            files = {}
            for item in fixture.FILES:
                path = root / item
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic helper bytes")
                files[item] = hashlib.sha256(path.read_bytes()).hexdigest()

            def save(mapping):
                raw = json.dumps(mapping).encode()
                (root / "private-sources.json").write_bytes(raw)
                return hashlib.sha256(raw).hexdigest()

            expected = save(files)
            self.assertEqual(set(fixture.sources(root, expected)), set(fixture.FILES))
            (root / fixture.FILES[0]).write_bytes(b"changed helper")
            with self.assertRaises(RuntimeError):
                fixture.sources(root, expected)
            for mapping in (
                {key: value for key, value in files.items() if key != fixture.FILES[0]},
                {**files, "unreviewed.py": "0" * 64},
            ):
                with self.assertRaises(RuntimeError):
                    fixture.sources(root, save(mapping))

    @unittest.skipUnless(
        os.name == "posix", "Linux selector/pipe fixture requires native offline run"
    )
    def test_plain_dump_reader_caps_memory_and_reaps_process(self):
        real_popen = subprocess.Popen
        created = []
        for amount in (65537, 8 * 1024 * 1024 + 1):

            def child(command, **kwargs):
                self.assertEqual(
                    command[:3],
                    ["/usr/bin/docker", "--host=unix:///var/run/docker.sock", "exec"],
                )
                result = real_popen(
                    [
                        sys.executable,
                        "-E",
                        "-s",
                        "-B",
                        "-c",
                        f"import sys;sys.stdout.buffer.write(b'x'*{amount})",
                    ],
                    stdin=kwargs["stdin"],
                    stdout=kwargs["stdout"],
                    stderr=kwargs["stderr"],
                    env=os.environ.copy(),
                )
                created.append(result)
                return result

            with (
                self.subTest(amount=amount),
                patch.object(fixture.subprocess, "Popen", side_effect=child),
            ):
                if amount > 8 * 1024 * 1024:
                    with self.assertRaises(RuntimeError):
                        fixture.dump_application("synthetic-owned-pg", {})
                else:
                    self.assertEqual(
                        fixture.dump_application("synthetic-owned-pg", {}),
                        b"x" * amount,
                    )
            self.assertIsNotNone(created[-1].poll())
            self.assertTrue(created[-1].stdout.closed)


if __name__ == "__main__":
    unittest.main()
