"""Source loader, framing and restore-command denials; no SSH/Docker/SQL runs."""

from dataclasses import replace
import ast
import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import adapter_package as package
from authority_sql_adapter import NativeSQLAdapter
from authority_test_fixtures import fixture, verifier
import authority_bridge as bridge

ROOT = Path(__file__).parent


def verifier_modules():
    sys.path.insert(0, str(ROOT / "sql-verifier"))
    import verifier_controller
    import verifier_setup
    from verifier_process import Failure
    from verifier_resources import Resources

    return verifier_controller, verifier_setup, Failure, Resources


controller, setup, Failure, Resources = verifier_modules()


class VerifierGuards(unittest.TestCase):
    def setUp(self):
        self.files = package.source_files(ROOT / "sql-verifier")
        self.pin = hashlib.sha256(package.manifest(self.files)).hexdigest()
        self.expected, _, _, self.raw, _ = fixture()
        self.expected = replace(self.expected, restore_verifier_sha256=self.pin)

    def test_default_loader_and_controller_do_not_execute_any_action(self):
        for script in (
            ROOT / "authority_sql_adapter.py",
            ROOT / "sql-verifier/verifier_controller.py",
        ):
            result = subprocess.run(
                [sys.executable, "-B", str(script)],
                capture_output=True,
                check=True,
                timeout=5,
            )
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "prepared_only")

    def test_explicit_CLI_rejects_unreviewed_manifest_before_input_or_transport(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "authority_sql_adapter.py"),
                "--execute",
                "--manifest-sha256",
                "0" * 64,
                "--image",
                self.expected.runtime_image,
            ],
            input=b"",
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 2)

    def test_framing_is_keyless_and_rejects_truncation_or_trailing_data(self):
        _, contents, _, _, _ = fixture()
        public = {
            name: getattr(self.expected, name) for name in controller.PUBLIC_FIELDS
        }
        data = package.packet(
            {
                "expected": public,
                "image": self.expected.runtime_image,
                "seconds": 90,
                "run": "aqua-authority-verify-" + "a" * 24,
            },
            package.pack(self.files),
            b"PGDMPsynthetic",
            contents["checkpoints.bin"],
        )
        header, source, dump, chain = package.read_packet(io.BytesIO(data))
        self.assertEqual(set(header["expected"]), controller.PUBLIC_FIELDS)
        self.assertNotIn("signing.key", header["expected"])
        self.assertNotIn("identity.key", header["expected"])
        self.assertEqual(dump, b"PGDMPsynthetic")
        self.assertEqual(chain, contents["checkpoints.bin"])
        self.assertEqual(package.unpack(source, self.pin), self.files)
        for wrong in (data[:-1], data + b"unexpected"):
            with self.assertRaises(ValueError):
                package.read_packet(io.BytesIO(wrong))

    def test_loader_checks_every_source_byte_before_compiling_or_transport(self):
        with tempfile.TemporaryDirectory() as raw:
            copy = Path(raw) / "source"
            shutil.copytree(ROOT / "sql-verifier", copy)
            target = copy / "verifier_process.py"
            target.write_text(
                target.read_text()
                + "\nraise AssertionError('unverified code executed')\n"
            )
            with self.assertRaisesRegex(ValueError, "manifest_mismatch"):
                NativeSQLAdapter(copy, self.pin, self.expected.runtime_image)

    def test_source_archive_links_traversal_duplicates_and_unhashed_changes_fail(self):
        raw = package.pack(self.files)
        self.assertEqual(package.unpack(raw, self.pin), self.files)
        for name, symlink in (("../bad.py", False), ("verifier_process.py", True)):
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode="w") as archive:
                item = tarfile.TarInfo(name)
                if symlink:
                    item.type, item.linkname = tarfile.SYMTYPE, "/private/key"
                else:
                    item.size = 1
                archive.addfile(item, None if symlink else io.BytesIO(b"x"))
            with self.assertRaises(ValueError):
                package.unpack(output.getvalue(), self.pin)

    def test_source_recheck_rejects_changed_files_before_ssh(self):
        with tempfile.TemporaryDirectory() as raw:
            copy = Path(raw) / "source"
            shutil.copytree(ROOT / "sql-verifier", copy)
            adapter = NativeSQLAdapter(copy, self.pin, self.expected.runtime_image)
            adapter.preflight(self.expected)
            (copy / "verifier_setup.py").write_text(
                "raise RuntimeError('changed source')\n"
            )
            with patch.object(bridge.host, "ssh_command") as ssh:
                with self.assertRaises(ValueError):
                    adapter.preflight(self.expected)
            ssh.assert_not_called()

    def test_no_receipt_only_callback_can_claim_actual_SQL_restore(self):
        def forged(*args):
            return {**verifier(*args), "mode": "actual_disposable_restore"}

        with self.assertRaisesRegex(
            bridge.stream.BackupError, "source_bound_adapter_required"
        ):
            bridge.verify_ram(self.raw, self.expected, forged, 60)

    def test_public_expected_keys_exclude_private_key_members(self):
        public = {
            name: getattr(self.expected, name) for name in controller.PUBLIC_FIELDS
        }
        chain = bytes.fromhex(self.expected.head_hex)
        public["protected_chain_sha256"] = hashlib.sha256(chain).hexdigest()
        controller.checked_request(public, chain, self.expected.runtime_image, self.pin)
        for key in ("identity.key", "signing.key", "private_seed", "hmac_material"):
            with self.subTest(key=key), self.assertRaises(Failure):
                controller.checked_request(
                    {**public, key: "not allowed"},
                    chain,
                    self.expected.runtime_image,
                    self.pin,
                )

    def test_restore_uses_six_exact_tables_and_non_super_INSERT_only_role(self):
        class Owned:
            name = "aqua-authority-verify-" + "a" * 24
            calls = []

            def call(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return (
                    b"\n".join(
                        f"{i}; 0 {100+i} TABLE DATA retirement {name} aqua_retirement_owner".encode()
                        for i, name in enumerate(setup.TABLES, 1)
                    )
                    if "--list" in args
                    else b""
                )

        owned = Owned()
        setup.restore(owned, b"PGDMPpublic-synthetic-dump")
        self.assertEqual(len(owned.calls), 7)
        self.assertIn("--list", owned.calls[0][0])
        observed = []
        for args, options in owned.calls[1:]:
            for flag in (
                "--exit-on-error",
                "--data-only",
                "--no-owner",
                "--no-privileges",
                "--strict-names",
                "--schema=retirement",
            ):
                self.assertIn(flag, args)
            self.assertEqual(args[args.index("-U") + 1], "aqua_retirement_restore")
            tables = [a for a in args if a.startswith("--table=")]
            self.assertEqual(len(tables), 1)
            observed.append(tables[0].removeprefix("--table="))
            self.assertNotIn("--disable-triggers", args)
            self.assertNotIn("--role=aqua_retirement_owner", args)
            self.assertEqual(options["data"], b"PGDMPpublic-synthetic-dump")
        self.assertEqual(
            observed,
            ["control", "owners", "intents", "pages", "fingerprints", "journal"],
        )

    def test_incomplete_or_extra_table_dump_is_rejected_before_restore(self):
        for names in (
            setup.TABLES[:-1],
            (*setup.TABLES, "extra"),
            (*setup.TABLES, "control"),
        ):

            class Owned:
                name = "owned-pg"
                calls = 0

                def call(self, *args, **kwargs):
                    self.calls += 1
                    return b"\n".join(
                        f"{i}; 0 {i} TABLE DATA retirement {name} owner".encode()
                        for i, name in enumerate(names, 1)
                    )

            owned = Owned()
            with self.subTest(names=names), self.assertRaises(Failure):
                setup.restore(owned, b"PGDMPsynthetic")
            self.assertEqual(owned.calls, 1)

    def test_unowned_id_and_daemon_failure_never_become_absence(self):
        resources = Resources(
            "aqua-authority-verify-" + "b" * 24, self.expected.runtime_image, 60
        )
        name = resources.name + "-pg"
        for raw in (
            b"Cannot connect to Docker daemon",
            b"No such container: foreign",
            b"daemon failed\nNo such container: " + name.encode(),
        ):
            with patch("verifier_resources.bounded", return_value=(1, raw)):
                with self.assertRaises(Failure):
                    resources.inspect("pg")
        with patch(
            "verifier_resources.bounded",
            return_value=(
                1,
                b"[]\nError response from daemon: No such container: " + name.encode(),
            ),
        ):
            self.assertIsNone(resources.inspect("pg"))

    def test_same_name_new_ID_and_renamed_original_ID_cannot_report_cleanup(self):
        resources = Resources(
            "aqua-authority-verify-" + "c" * 24, self.expected.runtime_image, 60
        )
        original = "a" * 64
        resources.created["pg"] = original
        resources.attempted = ["pg"]
        metadata = b"\n".join(
            json.dumps(value).encode()
            for value in (
                "b" * 64,
                "/" + resources.name + "-pg",
                {
                    "io.aqua.run": resources.name,
                    "io.aqua.purpose": "authority-sql-restore",
                },
            )
        )
        with patch("verifier_resources.bounded", return_value=(0, metadata)):
            with self.assertRaises(Failure):
                resources.inspect("pg")
        with (
            patch.object(resources, "inspect", return_value=None),
            patch.object(resources, "call", return_value=original.encode()),
        ):
            self.assertEqual(resources.cleanup(), [resources.name + "-pg"])

    def test_actual_controller_SIGTERM_and_repeat_finishes_red_owned_cleanup(self):
        program = r"""
import json,os,signal,stat,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()/'sql-verifier'))
import verifier_controller as c
from authority_test_fixtures import fixture
from dataclasses import replace
expected,contents,profile,raw,meta=fixture()
public={name:getattr(expected,name) for name in c.PUBLIC_FIELDS}
chain=contents['checkpoints.bin'];cleaned=[]
class Owned:
 def __init__(self,*args):pass
 def call(self,*args):return expected.runtime_image.encode()
 def cleanup(self):
  os.kill(os.getpid(),signal.SIGTERM)
  cleaned.append(True)
  return []
def work(*args):os.kill(os.getpid(),signal.SIGTERM)
binary=SimpleNamespace(st_mode=stat.S_IFREG|0o755,st_uid=0)
socket=SimpleNamespace(st_mode=stat.S_IFSOCK|0o660,st_uid=0)
with patch.object(c.sys,'platform','linux'),patch.object(c.os,'geteuid',return_value=1000),patch.object(c.os,'stat',return_value=binary),patch.object(c.os,'lstat',return_value=socket),patch.object(c,'Resources',Owned),patch.object(c,'initialize',side_effect=work):
 result=c.execute({},b'PGDMPpublic',chain,public,expected.runtime_image,expected.restore_verifier_sha256,90)
assert cleaned==[True] and result['status']=='failed' and result['cleanup']=='removed_and_absence_confirmed' and result['remaining_ids']==[]
print(json.dumps({'controlled_SIGTERM_and_cleanup_repeat':'passed','Docker_SSH_DB_actions':0}))
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", program],
            cwd=ROOT,
            capture_output=True,
            timeout=6,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(
            json.loads(result.stdout)["controlled_SIGTERM_and_cleanup_repeat"], "passed"
        )


TOC_ORDER = ("control", "fingerprints", "intents", "journal", "owners", "pages")

DEPENDENCIES = {
    "control": set(),
    "owners": set(),
    "intents": {"owners"},
    "pages": {"intents"},
    "fingerprints": {"intents"},
    "journal": {"intents"},
}

DUMP = b"PGDMPpublic-synthetic-RAM-only"


class Owned:
    name = "aqua-authority-verify-" + "a" * 24

    def __init__(self, toc=TOC_ORDER, fail=None):
        self.toc, self.fail = toc, fail
        self.seen, self.calls = set(), []

    def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if "--list" in args:
            return b"\n".join(
                f"{index}; 0 {index} TABLE DATA retirement {table} aqua_retirement_owner".encode()
                for index, table in enumerate(self.toc, 1)
            )
        # pg_restore selection honors archive TOC order, not repeated flag order.
        selected = [table for table in self.toc if "--table=" + table in args]
        for table in selected:
            if not DEPENDENCIES[table] <= self.seen:
                raise Failure("verifier_restore_foreign_key_violation")
            if table == self.fail:
                raise Failure("modeled_table_restore_failure")
            self.seen.add(table)
        return b""


class OrderedRestoreGuards(unittest.TestCase):
    def test_naive_multi_table_selection_keeps_TOC_order_and_reproduces_FK_conflict(
        self,
    ):
        owned = Owned()
        with self.assertRaisesRegex(Failure, "foreign_key"):
            owned.call("pg_restore", *("--table=" + t for t in setup.TABLES), data=DUMP)
        self.assertEqual(len(owned.calls), 1)

    def test_new_restore_selects_one_table_in_exact_parent_order_same_role_data(self):
        owned = Owned()
        result = setup.restore(owned, DUMP)
        self.assertEqual(owned.seen, set(setup.TABLES))
        self.assertEqual(len(owned.calls), 7)
        observed = []
        for args, options in owned.calls[1:]:
            tables = [
                arg.removeprefix("--table=")
                for arg in args
                if arg.startswith("--table=")
            ]
            self.assertEqual(len(tables), 1)
            observed.extend(tables)
            self.assertEqual(args[args.index("-U") + 1], "aqua_retirement_restore")
            self.assertTrue(
                all(
                    flag in args
                    for flag in (
                        "--data-only",
                        "--no-owner",
                        "--no-privileges",
                        "--strict-names",
                        "--schema=retirement",
                        "--exit-on-error",
                    )
                )
            )
            self.assertNotIn("--disable-triggers", args)
            self.assertFalse(any("session_replication_role" in arg for arg in args))
            self.assertEqual(options, {"data": DUMP})
        self.assertEqual(tuple(observed), setup.TABLES)
        listing = Owned().call("--list")
        self.assertEqual(result, hashlib.sha256(listing).hexdigest())

    def test_missing_duplicate_or_extra_table_is_rejected_before_data(self):
        for toc in (
            TOC_ORDER[:-1],
            (*TOC_ORDER, "extra"),
            (*TOC_ORDER[:-1], "control"),
        ):
            owned = Owned(toc=toc)
            with self.subTest(toc=toc), self.assertRaises(Failure):
                setup.restore(owned, DUMP)
            self.assertEqual(len(owned.calls), 1)

    def test_first_table_failure_stops_without_loading_subsequent_tables(self):
        owned = Owned(fail="pages")
        with self.assertRaisesRegex(Failure, "modeled_table"):
            setup.restore(owned, DUMP)
        self.assertEqual(owned.seen, {"control", "owners", "intents"})
        self.assertEqual(len(owned.calls), 5)


SOURCE = ROOT / "sql-verifier"


def diagnostic_codes():
    from verifier_process import PROBE_CODES

    return PROBE_CODES


PROBE_CODES = diagnostic_codes()


class DurableProbeGuards(unittest.TestCase):
    def test_create_failure_and_started_probe_failure_keep_distinct_safe_phases(self):
        expected, contents, _, _, _ = fixture()
        public = {name: getattr(expected, name) for name in controller.PUBLIC_FIELDS}
        binary = SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0)
        socket = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660, st_uid=0)
        for phase in ("probe_create", "probe_run"):

            class Owned:
                budget = SimpleNamespace(remaining=lambda: 10)

                def call(self, *args):
                    return expected.runtime_image.encode()

                def create(self, *args):
                    if phase == "probe_create":
                        raise Failure("verifier_docker_failed")
                    return "owned-probe-ID"

                def cleanup(self):
                    return []

            with (
                self.subTest(phase=phase),
                patch.object(controller.sys, "platform", "linux"),
                patch.object(controller.os, "geteuid", return_value=1000),
                patch.object(controller.os, "stat", return_value=binary),
                patch.object(controller.os, "lstat", return_value=socket),
                patch.object(controller, "Resources", return_value=Owned()),
                patch.object(controller, "initialize", return_value=b"c" * 64),
                patch.object(controller, "restore", return_value="d" * 64),
                patch.object(controller, "sql", return_value=b"c" * 64),
                patch.object(
                    controller,
                    "probe_run",
                    side_effect=Failure("verifier_docker_failed"),
                ) as run,
            ):
                result = controller.execute(
                    {},
                    b"PGDMPpublic",
                    contents["checkpoints.bin"],
                    public,
                    expected.runtime_image,
                    expected.restore_verifier_sha256,
                    90,
                )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["phase"], phase)
            self.assertEqual(result["failure_code"], "verifier_docker_failed")
            self.assertEqual(result["cleanup"], "removed_and_absence_confirmed")
            self.assertEqual(result["remaining_ids"], [])
            self.assertEqual(run.called, phase == "probe_run")

    def test_codes_are_only_existing_literal_failures_or_fixed_unknown(self):
        found = set()
        for name in ["verifier_probe.py", "verifier_validation.py"]:
            for node in ast.walk(ast.parse((SOURCE / name).read_bytes())):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "Failure"
                ):
                    self.assertEqual(len(node.args), 1)
                    found.add(ast.literal_eval(node.args[0]))
        self.assertEqual(PROBE_CODES, found | {"unclassified_failure"})

    def test_exact_known_failure_is_forwarded_with_same_start_caps(self):
        resources = SimpleNamespace(budget=SimpleNamespace(remaining=lambda: 17.25))
        reply = {
            "status": "failed",
            "probe_subphase": "privileges",
            "probe_failure_code": "verifier_backup_role_invalid",
        }
        report = {}
        with patch.object(
            controller, "bounded", return_value=(1, json.dumps(reply).encode())
        ) as bounded:
            with self.assertRaisesRegex(Failure, "^verifier_docker_failed$"):
                controller.probe_run(
                    resources, "owned-ID", b"same-public-package", report
                )
        self.assertEqual(report, {k: v for k, v in reply.items() if k != "status"})
        self.assertEqual(
            bounded.call_args.args[0],
            controller.DOCKER + ["start", "--attach", "--interactive", "owned-ID"],
        )
        self.assertEqual(
            bounded.call_args.kwargs,
            {"data": b"same-public-package", "seconds": 17.25, "maximum": 65536},
        )

    def test_unrecognized_extra_or_dynamic_output_stays_RAM(self):
        resources = SimpleNamespace(budget=SimpleNamespace(remaining=lambda: 10))
        fixed = {
            "status": "failed",
            "probe_subphase": "chain",
            "probe_failure_code": "unclassified_failure",
        }
        for value in [
            b"untrusted stderr SQL/key sentinel",
            json.dumps({**fixed, "raw_error": "untrusted sentinel"}).encode(),
            json.dumps({**fixed, "probe_failure_code": "untrusted sentinel"}).encode(),
            json.dumps({**fixed, "probe_subphase": "untrusted sentinel"}).encode(),
            json.dumps({**fixed, "status": "passed"}).encode(),
            b"[]",
        ]:
            report = {}
            with patch.object(controller, "bounded", return_value=(1, value)):
                with self.assertRaises(Failure):
                    controller.probe_run(resources, "owned-ID", b"public", report)
            self.assertEqual(report, {})

    def test_actual_own_python_import_failure_emits_no_exception_text(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp)
            (fake / "psycopg.py").write_text(
                "raise RuntimeError('untrusted import sentinel')\n"
            )
            code = (
                "import runpy,sys;sys.path[:0]="
                + repr([str(fake), str(SOURCE)])
                + ";sys.argv=['verifier_probe.py','5'];runpy.run_path("
                + repr(str(SOURCE / "verifier_probe.py"))
                + ",run_name='__main__')"
            )
            result = subprocess.run(
                [sys.executable, "-B", "-c", code], capture_output=True, timeout=8
            )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(
            json.loads(result.stdout),
            {
                "status": "failed",
                "probe_subphase": "imports",
                "probe_failure_code": "unclassified_failure",
            },
        )

    def test_bootstrap_rejects_invalid_archive_with_fixed_metadata_only(self):
        result = subprocess.run(
            [sys.executable, "-B", "-c", controller.BOOTSTRAP, "5"],
            input=b"not a tar archive",
            capture_output=True,
            timeout=8,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(
            json.loads(result.stdout),
            {
                "status": "failed",
                "probe_subphase": "bootstrap",
                "probe_failure_code": "unclassified_failure",
            },
        )


if __name__ == "__main__":
    unittest.main()
