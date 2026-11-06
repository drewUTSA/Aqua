"""Offline native80 wrapper guards; Docker is mocked, streams use own Python."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_retirement_native as native
import run_retirement_operator as operator
import run_retirement_fixture_guards as fixtures
import run_retirement_backup_models as backups

NAME = "aqua-native-protocol-" + "a" * 24
IDENT = "b" * 64
IMAGE = "sha256:" + "c" * 64


def archive(name="backend/example.py", *, link=False):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as result:
        item = tarfile.TarInfo(name)
        if link:
            item.type, item.linkname = tarfile.SYMTYPE, "/private/env"
            result.addfile(item)
        else:
            item.size = 4
            result.addfile(item, io.BytesIO(b"pass"))
    return output.getvalue()


def metadata(*, name=NAME, ident=IDENT, purpose=native.PURPOSE, run=NAME):
    return (
        b"\n".join(
            json.dumps(value).encode() for value in (ident, "/" + name, purpose, run)
        )
        + b"\n"
    )


class NativeTests(unittest.TestCase):
    def test_backup_selector_has_exact56_and_preserves_separate_namespaces(self):
        value = {**native.COUNTS, "tests": 56}
        self.assertEqual(
            native.result_counts(json.dumps(value).encode(), "backups56"), value
        )
        self.assertEqual(len(backups.EXPECTED_IDS), len(set(backups.EXPECTED_IDS)))
        self.assertEqual(
            [len(backups.expected(group)) for group in backups.GROUPS], [46, 10]
        )
        for changes in (
            {"tests": 55},
            {"tests": 57},
            {"skipped": 1},
            {"tests": 56.0},
            {"errors": False},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                native.result_counts(
                    json.dumps({**value, **changes}).encode(), "backups56"
                )
        for other in ("protocol80", "archival9", "operator77", "fixtures36"):
            with self.assertRaises(ValueError):
                native.result_counts(json.dumps(value).encode(), other)

    def test_backup_source_allows_only_its_exact_bounded_public_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            manifest = root / native.CLIENT_MANIFEST
            manifest.parent.mkdir(parents=True)
            manifest.write_bytes(b"{}")
            baseline = archive()
            with (
                patch.object(native, "ROOT", root),
                patch.object(native, "source_archive", return_value=baseline),
            ):
                source = native.suite_source("backups56")
                self.assertEqual(
                    native.prepared(source, "backups56")["expected_tests"], 56
                )
                with tarfile.open(fileobj=io.BytesIO(source)) as packed:
                    self.assertEqual(
                        set(packed.getnames()),
                        {"backend/example.py", native.CLIENT_MANIFEST},
                    )
                for other in ("protocol80", "archival9", "fixtures36"):
                    self.assertEqual(native.suite_source(other), baseline)
                    with self.assertRaises(ValueError):
                        native.prepared(source, other)
                with self.assertRaises(ValueError):
                    native.prepared(baseline, "backups56")
                manifest.write_bytes(b"x" * 131073)
                with self.assertRaises(ValueError):
                    native.suite_source("backups56")
                manifest.unlink()
                elsewhere = root / "other.json"
                elsewhere.write_bytes(b"{}")
                manifest.symlink_to(elsewhere)
                with self.assertRaises(ValueError):
                    native.suite_source("backups56")
        with self.assertRaises(ValueError):
            native.prepared(
                archive("ops/retirement/backup_client/other.json"), "backups56"
            )

    def test_backup_group_report_cannot_hide_skips_errors_or_unknown_fields(self):
        value = {
            "status": "passed",
            "tests": 46,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
        }
        self.assertTrue(backups.valid_counts(value, 46))
        for changes in (
            {"status": "failed"},
            {"tests": 45},
            {"tests": 46.0},
            {"errors": False},
            {"skipped": 1},
            {"raw_error": "private-sentinel"},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(backups.valid_counts({**value, **changes}, 46))

    def test_default_prepares_public_source_without_docker_or_output(self):
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["native"]),
            patch.object(native, "source_archive", return_value=archive()),
            patch.object(native.subprocess, "run") as docker,
            patch.object(native.subprocess, "Popen") as child,
            redirect_stdout(output),
        ):
            self.assertEqual(native.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "prepared")
        docker.assert_not_called()
        child.assert_not_called()

    def test_archive_rejects_secret_paths_traversal_links_and_excess_input(self):
        for name in (
            "../backend/a.py",
            "/backend/a.py",
            "backend/.env.py",
            "backend/private.env",
            "tools/other/a.py",
            "secrets/a.py",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                native.prepared(archive(name))
        with self.assertRaises(ValueError):
            native.prepared(archive(link=True))
        with self.assertRaises(ValueError):
            native.prepared(b"x" * (native.MAX_SOURCE + 1))
        self.assertEqual(native.prepared(archive())["expected_tests"], 80)

    def test_only_exact80_no_skips_errors_or_truthy_counts_can_pass(self):
        good = json.dumps(native.COUNTS).encode()
        self.assertEqual(
            native.result_counts(b"ordinary unittest summary\n" + good + b"\n"),
            native.COUNTS,
        )
        for changes in (
            {"tests": 79},
            {"tests": 81},
            {"skipped": 1},
            {"errors": 1},
            {"failures": False},
            {"tests": 80.0},
            {"extra": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                native.result_counts(json.dumps({**native.COUNTS, **changes}).encode())
        with self.assertRaises(ValueError):
            native.result_counts(good[:-1] + b',"tests":80}')

    def test_missing_requires_exact_container_kind_reference_and_daemon_success(self):
        for reference in (NAME, IDENT):
            result = SimpleNamespace(
                returncode=1,
                stdout=b"",
                stderr=(
                    "Error response from daemon: No such container: " + reference + "\n"
                ).encode(),
            )
            with patch.object(native.subprocess, "run", return_value=result):
                self.assertIsNone(native.owned(NAME, reference))
        for error in (
            b"Cannot connect to the Docker daemon",
            b"No such image: " + NAME.encode(),
            b"No such container: unrelated",
            b"unrelated failure\nNo such container: " + NAME.encode(),
        ):
            with (
                self.subTest(error=error),
                patch.object(
                    native.subprocess,
                    "run",
                    return_value=SimpleNamespace(
                        returncode=1, stdout=b"", stderr=error
                    ),
                ),
                self.assertRaises(RuntimeError),
            ):
                native.owned(NAME, NAME)

    def test_closed_suite_selection_cannot_choose_an_arbitrary_program(self):
        for value in ("../other.py", "/tmp/program.py", "archival8", None, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                native.prepared(archive(), value)

    def test_archival_and_protocol_counts_cannot_satisfy_each_other(self):
        archival = {**native.COUNTS, "tests": 9}
        self.assertEqual(
            native.result_counts(json.dumps(archival).encode(), "archival9"), archival
        )
        for suite, counts in (("archival9", native.COUNTS), ("protocol80", archival)):
            with self.subTest(suite=suite), self.assertRaises(ValueError):
                native.result_counts(json.dumps(counts).encode(), suite)
        for changes in (
            {"skipped": 1},
            {"tests": 8},
            {"tests": 10},
            {"tests": 9.0},
            {"failures": False},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                native.result_counts(
                    json.dumps({**archival, **changes}).encode(), "archival9"
                )

    def test_operator_selector_has_exact77_and_retains_all_other_counts(self):
        counts = {**native.COUNTS, "tests": 77}
        self.assertEqual(
            native.result_counts(json.dumps(counts).encode(), "operator77"), counts
        )
        for change in (
            {"tests": 76},
            {"tests": 78},
            {"skipped": 1},
            {"errors": 1},
            {"tests": 77.0},
            {"failures": False},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                native.result_counts(
                    json.dumps({**counts, **change}).encode(), "operator77"
                )
        for suite in ("archival9", "protocol80"):
            with self.assertRaises(ValueError):
                native.result_counts(json.dumps(counts).encode(), suite)

    def test_only_operator_source_adds_exact_bounded_public_HBA(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            hba = root / native.HBA
            hba.parent.mkdir(parents=True)
            raw = b"# public synthetic HBA\nlocal all all reject\n"
            hba.write_bytes(raw)
            baseline = archive()
            with (
                patch.object(native, "ROOT", root),
                patch.object(native, "source_archive", return_value=baseline),
            ):
                for suite in ("protocol80", "archival9"):
                    self.assertEqual(native.suite_source(suite), baseline)
                source = native.suite_source("operator77")
                self.assertEqual(
                    native.prepared(source, "operator77")["expected_tests"], 77
                )
                with tarfile.open(fileobj=io.BytesIO(source)) as packed:
                    self.assertEqual(
                        packed.getnames(), ["backend/example.py", native.HBA]
                    )
                    self.assertEqual(packed.extractfile(native.HBA).read(), raw)
                for suite in ("protocol80", "archival9"):
                    with self.assertRaises(ValueError):
                        native.prepared(source, suite)
                hba.unlink()
                hba.symlink_to(root / "backend-secret.env")
                with self.assertRaises(ValueError):
                    native.suite_source("operator77")
        with self.assertRaises(ValueError):
            native.prepared(archive(), "operator77")
        for name in (
            "ops/other/pg_hba.conf",
            "ops/appdb/private.conf",
            "ops/appdb/pg_hba.conf/../private.conf",
        ):
            with self.assertRaises(ValueError):
                native.prepared(archive(name), "operator77")
        oversized = io.BytesIO()
        with tarfile.open(fileobj=oversized, mode="w") as packed:
            item = tarfile.TarInfo(native.HBA)
            item.size = 131073
            packed.addfile(item, io.BytesIO(b"x" * item.size))
        with self.assertRaises(ValueError):
            native.prepared(oversized.getvalue(), "operator77")

    def test_operator_entry_rejects_missing_extra_duplicate_or_changed_identity(self):
        class Case(unittest.TestCase):
            def __init__(self, identity):
                super().__init__()
                self.identity = identity

            def id(self):
                return self.identity

        def suite(names):
            return unittest.TestSuite(Case(name) for name in names)

        self.assertEqual(len(operator.EXPECTED_IDS), 77)
        valid = suite(operator.EXPECTED_IDS)
        self.assertIs(operator.checked_suite(valid), valid)
        for names in (
            operator.EXPECTED_IDS[:-1],
            operator.EXPECTED_IDS + ("extra.test",),
            operator.EXPECTED_IDS[:-1] + (operator.EXPECTED_IDS[0],),
            operator.EXPECTED_IDS[:-1] + ("changed.test",),
        ):
            with self.assertRaises(RuntimeError):
                operator.checked_suite(suite(names))
        for args in (["operator", "arbitrary.py"], ["operator", "--suite", "other"]):
            with (
                patch.object(operator.sys, "argv", args),
                self.assertRaises(RuntimeError),
            ):
                operator.main()

    def test_fixture_selector_is_closed_exact36_without_altering_other_suites(self):
        expected = {**native.COUNTS, "tests": 36}
        self.assertEqual(
            native.result_counts(json.dumps(expected).encode(), "fixtures36"), expected
        )
        baseline = archive()
        with patch.object(native, "source_archive", return_value=baseline):
            self.assertEqual(native.suite_source("fixtures36"), baseline)
        with self.assertRaises(ValueError):
            native.prepared(archive(native.HBA), "fixtures36")
        for changes in (
            {"tests": 35},
            {"tests": 37},
            {"skipped": 1},
            {"errors": 1},
            {"tests": 36.0},
            {"failures": False},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                native.result_counts(
                    json.dumps({**expected, **changes}).encode(), "fixtures36"
                )
        for other in ("protocol80", "archival9", "operator77"):
            with self.assertRaises(ValueError):
                native.result_counts(json.dumps(expected).encode(), other)

        class Case(unittest.TestCase):
            def __init__(self, identity):
                super().__init__()
                self.identity = identity

            def id(self):
                return self.identity

        def suite(names):
            return unittest.TestSuite(Case(name) for name in names)

        valid = suite(fixtures.EXPECTED_IDS)
        self.assertEqual(len(fixtures.MODULES), 5)
        self.assertEqual(len(fixtures.EXPECTED_IDS), 36)
        self.assertIs(fixtures.checked_suite(valid), valid)
        for names in (
            fixtures.EXPECTED_IDS[:-1],
            fixtures.EXPECTED_IDS + ("extra.test",),
            fixtures.EXPECTED_IDS[:-1] + (fixtures.EXPECTED_IDS[0],),
            fixtures.EXPECTED_IDS[:-1] + ("changed.test",),
        ):
            with self.assertRaises(RuntimeError):
                fixtures.checked_suite(suite(names))
        with (
            patch.object(fixtures.sys, "argv", ["fixture", "arbitrary.py"]),
            patch.object(fixtures.sys, "platform", "linux"),
            patch.object(fixtures.os, "geteuid", return_value=1000),
            self.assertRaises(RuntimeError),
        ):
            fixtures.main()

    def test_owner_name_id_and_both_labels_are_required(self):
        with patch.object(
            native.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout=metadata()),
        ):
            self.assertEqual(native.owned(NAME, NAME), IDENT)
        for values in (
            {"name": "unrelated"},
            {"purpose": "other"},
            {"run": "other"},
            {"ident": "d" * 64},
        ):
            with (
                self.subTest(values=values),
                patch.object(
                    native.subprocess,
                    "run",
                    return_value=SimpleNamespace(
                        returncode=0, stdout=metadata(**values)
                    ),
                ),
                self.assertRaises(RuntimeError),
            ):
                native.owned(NAME, IDENT)

    def test_cleanup_resolves_lost_remove_but_not_lost_create_or_wrong_id(self):
        with (
            patch.object(native, "owned", side_effect=[IDENT, None, None]) as inspect,
            patch.object(native, "command", side_effect=RuntimeError("lost")) as remove,
        ):
            self.assertTrue(native.cleanup(NAME, IDENT))
            remove.assert_called_once_with("container", "rm", "--force", IDENT)
            self.assertEqual(inspect.call_args_list[-1].args, (NAME, IDENT))
        with (
            patch.object(native, "owned", return_value=None),
            patch.object(native, "command") as remove,
        ):
            self.assertFalse(native.cleanup(NAME, None))
            remove.assert_not_called()
        with (
            patch.object(native, "owned", return_value="d" * 64),
            patch.object(native, "command") as remove,
        ):
            self.assertFalse(native.cleanup(NAME, IDENT))
            remove.assert_not_called()

    def test_success_keeps_original_caps_no_host_mount_and_cleanup_required(self):
        calls = []

        def command(*args):
            calls.append(args)
            return (IMAGE if args[0] == "image" else IDENT).encode()

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "proof"
            with (
                patch.object(native, "command", side_effect=command),
                patch.object(native, "owned", side_effect=[None, IDENT]),
                patch.object(
                    native,
                    "stream",
                    return_value=(0, json.dumps(native.COUNTS).encode()),
                ),
                patch.object(native, "cleanup", return_value=True),
            ):
                report = native.execute(IMAGE, target, archive())
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["cleanup"], "removed_and_absence_confirmed")
            self.assertEqual(
                json.loads((target / "report.json").read_text())["counts"],
                native.COUNTS,
            )
        create = calls[-1]
        for option in (
            "--network=none",
            "--read-only",
            "--interactive",
            "--memory=128m",
            "--memory-swap=128m",
            "--cpus=1",
            "--user=1000:1000",
            "--pull=never",
        ):
            self.assertIn(option, create)
        self.assertFalse(
            any(
                value.startswith(("--mount", "--volume", "--publish", "--env-file"))
                for value in create
            )
        )
        self.assertIn(
            "--tmpfs=/checks:rw,nosuid,nodev,size=67108864,uid=1000,gid=1000,mode=0700",
            create,
        )

    def test_live_log_overflow_and_deadline_stop_only_owned_python_child(self):
        scripts = (
            "import sys;sys.stdin.buffer.read();print('x'*70000)",
            "import time;time.sleep(2)",
        )
        for script in scripts:
            with (
                self.subTest(script=script),
                tempfile.TemporaryDirectory() as directory,
                patch.object(native, "DOCKER", [sys.executable, "-c", script]),
                patch.object(native, "EXEC_SECONDS", 0.1),
            ):
                log = Path(directory) / "native.log"
                with self.assertRaises((RuntimeError, TimeoutError)):
                    native.stream(IDENT, b"source", log)
                self.assertLessEqual(log.stat().st_size, native.MAX_LOG)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                native,
                "DOCKER",
                [
                    sys.executable,
                    "-c",
                    "import sys;sys.stdin.buffer.read();print('bounded')",
                ],
            ),
        ):
            self.assertEqual(
                native.stream(IDENT, b"source", Path(directory) / "native.log"),
                (0, b"bounded\n"),
            )

    def test_cleanup_failure_or_cancellation_cannot_turn_exact80_into_green(self):
        for cancelled in (False, True):
            signals = {"cleaning": False, "cancelled": False}

            def clean(name, ident):
                self.assertTrue(signals["cleaning"])
                signals["cancelled"] = cancelled
                return cancelled

            with (
                self.subTest(cancelled=cancelled),
                tempfile.TemporaryDirectory() as directory,
                patch.object(
                    native, "command", side_effect=[IMAGE.encode(), IDENT.encode()]
                ),
                patch.object(native, "owned", side_effect=[None, IDENT]),
                patch.object(
                    native,
                    "stream",
                    return_value=(0, json.dumps(native.COUNTS).encode()),
                ),
                patch.object(native, "cleanup", side_effect=clean),
            ):
                report = native.execute(
                    IMAGE, Path(directory) / "proof", archive(), signals=signals
                )
            self.assertEqual(report["status"], "failed")
            self.assertEqual(
                report["cleanup"],
                "removed_and_absence_confirmed" if cancelled else "unconfirmed",
            )


if __name__ == "__main__":
    unittest.main()
