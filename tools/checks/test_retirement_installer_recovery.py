"""Pure QA-profile/receipt/ownership guards; no Docker or production files.

The owner-only file I/O is modeled in temporary files because this suite also
runs on a Mac UID. Native owner/mode/lock/SQL behavior remains an execution gate.
"""

from contextlib import contextmanager
import hashlib
import io
import json
import subprocess
import ast
import os
from pathlib import Path
import sys
import tempfile
import tarfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_retirement_installer_rehearsal as controller  # noqa: E402
from retirement_fixture import installer_rehearsal_resources as resources  # noqa: E402
from ops.retirement import operator_files  # noqa: E402

RUN = "aqua-retirement-host-" + "a" * 24
SOURCE = "b" * 64
CODE = "c" * 64
CHAIN = "d" * 64
PUBLIC = {
    "schemaVersion": 1,
    "installation_id": "00000000-0000-4000-8000-000000000001",
    "identity_key_id": "00000000-0000-4000-8000-000000000002",
    "key_commitment": "e" * 64,
    "public_key": "f" * 64,
    "runtime_image": resources.IMAGE,
    "source_sha256": SOURCE,
}
HEAD = {
    **PUBLIC,
    "sequence": 0,
    "event_digest": "0" * 64,
    "protected_chain_sha256": CHAIN,
}


def recovery(**changes):
    value = {
        "mode": "retained_authority_app_only",
        "protected_sha256": CHAIN,
        "ready": True,
        "pending_manifest": False,
        "events_verified": 0,
        "purge_batches": 0,
        "writers_resumed": False,
        "cron_resumed": False,
        "total_host_restore_supported": False,
        "total_host_authority_restore_supported": False,
        "physical_mail_validation": "child_owner_mode_readonly_named_inode",
    }
    return {**value, **changes}


class ArchiveInputTests(unittest.TestCase):
    def archive(self, entries):
        value = io.BytesIO()
        with tarfile.open(fileobj=value, mode="w") as packed:
            for name, raw in entries:
                item = tarfile.TarInfo(name)
                item.size = len(raw)
                packed.addfile(item, io.BytesIO(raw))
        raw = value.getvalue()
        return raw, hashlib.sha256(raw).hexdigest()

    def test_full_approved_source_accepts_exact_large_runtime_asset(self):
        from prepare_retirement_stage import checked_archive, full_source, LARGE_ASSET

        raw = full_source(ROOT)
        value = checked_archive(raw, hashlib.sha256(raw).hexdigest())
        asset = value[LARGE_ASSET]
        self.assertEqual(len(asset), 708370)
        self.assertEqual(
            hashlib.sha256(asset).hexdigest(),
            "a5b8b74b66c0ed54d90098285cb0dbe02217ae41d7c91f0c57cf4a761e14521a",
        )

    def test_large_asset_exception_never_accepts_different_bytes(self):
        from prepare_retirement_stage import checked_archive, LARGE_ASSET

        raw = (ROOT / LARGE_ASSET).read_bytes()
        for modified in (b"X" + raw[1:], raw[:-1]):
            with (
                self.subTest(size=len(modified)),
                self.assertRaisesRegex(
                    RuntimeError, "operator_stage_runtime_asset_changed"
                ),
            ):
                checked_archive(*self.archive([(LARGE_ASSET, modified)]))

    def test_other_large_members_remain_rejected_and_source_pin_is_required(self):
        from prepare_retirement_stage import checked_archive

        raw, expected = self.archive([("backend/unreviewed.py", b"x" * 262145)])
        with self.assertRaisesRegex(
            RuntimeError, "operator_stage_source_member_invalid"
        ):
            checked_archive(raw, expected)
        with self.assertRaisesRegex(
            RuntimeError, "operator_stage_full_source_pin_changed"
        ):
            checked_archive(raw, "0" * 64)


class PublicErrorTests(unittest.TestCase):
    def test_only_exact_source_known_preflight_categories_are_retained(self):
        for category in controller.PREFLIGHT_ERRORS:
            self.assertEqual(
                controller.public_error(RuntimeError(category)),
                {
                    "error_type": "RuntimeError",
                    "error_category": category,
                },
            )

    def test_arbitrary_private_text_arguments_and_subclasses_never_escape(self):
        class ForeignError(RuntimeError):
            pass

        for error in (
            RuntimeError("password=synthetic-private-sentinel"),
            RuntimeError("operator_stage_source_member_invalid", "private"),
            RuntimeError({"private": "value"}),
            ForeignError("operator_stage_source_member_invalid"),
        ):
            with self.subTest(type=type(error)):
                value = controller.public_error(error)
                self.assertEqual(set(value), {"error_type"})
                self.assertNotIn("private", json.dumps(value).lower())


class AckHostImportTests(unittest.TestCase):
    def prefix(self):
        from ops.retirement.install_resources import ack_program

        source = (ROOT / "ops/retirement/retirement_host.py").read_bytes()
        program = ack_program(source)
        prefix, separator, _ = program.partition(
            b"\nfrom retirement.checkpoint import ProtectedFile\n"
        )
        self.assertTrue(separator)
        return prefix

    def execute_prefix(self, prefix):
        old = sys.modules.get("_checked_host")
        try:
            with (
                patch.object(sys, "path", [str(ROOT / "backend"), *sys.path]),
                patch.object(
                    __import__("os"),
                    "open",
                    side_effect=AssertionError("host_import_private_open"),
                ),
            ):
                exec(compile(prefix, "source-checked-ack-prefix", "exec"), {})
            return sys.modules["_checked_host"]
        finally:
            if old is None:
                sys.modules.pop("_checked_host", None)
            else:
                sys.modules["_checked_host"] = old

    def test_exact_approved_host_source_imports_before_any_private_open(self):
        module = self.execute_prefix(self.prefix())
        self.assertEqual(module.__file__, "/operator/host-sources/retirement_host.py")
        self.assertTrue(callable(module.pool_for))
        self.assertTrue(callable(module.parse_settings))

    def test_retained_shallow_path_reproduces_failure_before_any_private_open(self):
        prefix = self.prefix().replace(
            b"/operator/host-sources/retirement_host.py",
            b"/operator/retirement_host.py",
            1,
        )
        with self.assertRaises(IndexError):
            self.execute_prefix(prefix)


class MountTargetTests(unittest.TestCase):
    def test_exact_materialize_targets_are_empty_single_link_owner0600_files(self):
        from ops.retirement import materialize

        expected = {
            "backend/checkpoints.bin",
            "backend/mail-worker.lock",
            "operator/public/checkpoints.bin",
            "operator/export/checkpoints.bin",
            "operator/export/identity.key",
            "operator/export/signing.key",
        }
        self.assertEqual(set(materialize.MOUNT_TARGETS), expected)
        # Real local inode/mode/create-only behavior. Owner follows the current
        # Mac UID here; actual materialize.create enforces native UID1000.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in expected:
                (root / name).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with patch.object(materialize, "ROOT", root):
                materialize.mount_targets()
            self.assertEqual(
                {
                    p.relative_to(root).as_posix()
                    for p in root.rglob("*")
                    if p.is_file()
                },
                expected,
            )
            for name in expected:
                path = root / name
                self.assertEqual(path.read_bytes(), b"")
                value = path.lstat()
                self.assertEqual(
                    (value.st_uid, value.st_mode & 0o777, value.st_nlink),
                    (os.getuid(), 0o600, 1),
                )

    def test_existing_target_is_not_overwritten_or_followed(self):
        from ops.retirement import materialize

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in materialize.MOUNT_TARGETS:
                (root / name).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target = root / materialize.MOUNT_TARGETS[0]
            target.write_bytes(b"public-existing-sentinel")
            with (
                patch.object(materialize, "ROOT", root),
                self.assertRaises(FileExistsError),
            ):
                materialize.mount_targets()
            self.assertEqual(target.read_bytes(), b"public-existing-sentinel")

    def test_actual_create_places_all_targets_before_parent_fsync(self):
        tree = ast.parse((ROOT / "ops/retirement/materialize.py").read_bytes())
        create = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "create"
        )
        calls = [n for n in ast.walk(create) if isinstance(n, ast.Call)]
        target = [
            n.lineno
            for n in calls
            if isinstance(n.func, ast.Name) and n.func.id == "mount_targets"
        ]
        sync = [
            n.lineno
            for n in calls
            if isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "os"
            and n.func.attr == "fsync"
        ]
        self.assertEqual(len(target), 1)
        self.assertTrue(sync)
        self.assertLess(target[0], min(sync))
        self.assertIn(
            "os.geteuid() != 1000", (ROOT / "ops/retirement/materialize.py").read_text()
        )


class ReceiptTests(unittest.TestCase):
    def test_minimal_genesis_receipt_is_accepted(self):
        self.assertEqual(controller.checked_recovery(recovery(), HEAD), recovery())

    def test_non_genesis_or_incomplete_state_never_passes(self):
        for changes in (
            {"events_verified": 1},
            {"purge_batches": 1},
            {"events_verified": False},
            {"purge_batches": False},
            {"ready": 1},
            {"pending_manifest": None},
            {"protected_sha256": "0" * 64},
        ):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                controller.checked_recovery(recovery(**changes), HEAD)

    def test_no_resume_total_loss_or_ex_claim_is_accepted(self):
        for name in (
            "writers_resumed",
            "cron_resumed",
            "total_host_restore_supported",
            "total_host_authority_restore_supported",
        ):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                controller.checked_recovery(recovery(**{name: True}), HEAD)
        with self.assertRaises(RuntimeError):
            controller.checked_recovery(
                recovery(physical_mail_validation="actual_same_inode_child_EX"), HEAD
            )
        missing = recovery()
        del missing["total_host_authority_restore_supported"]
        with self.assertRaises(RuntimeError):
            controller.checked_recovery(missing, HEAD)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.private = self.root / "installed"
        (self.private / "operator/export").mkdir(parents=True)
        self.stage = self.root / "stage"
        self.stage.mkdir()
        self.fixture = object.__new__(resources.Rehearsal)
        self.fixture.scope = SimpleNamespace(
            private=self.private,
            plan=self.root / "retirement-plan.json",
            validate=Mock(),
        )
        self.fixture.stage = self.stage
        self.fixture.image = resources.IMAGE
        self.fixture.source_sha256 = SOURCE
        self.fixture.capture_installed_checkpoint = Mock()
        self.fixture.owned = Mock(side_effect=lambda role: "1" * 64)
        self.fixture.passwords = {"runtime": "synthetic-runtime-only"}
        self.role_dsn = (
            b"postgresql://aqua_retirement_recovery:"
            + b"r" * 43
            + b"@/aqua_retirement?host=/run/aqua-app-db&port=5432&sslmode=disable"
        )
        self.inputs = {
            self.fixture.scope.plan: b"synthetic-plan",
            self.stage / "restore_session_fence.sql": b"synthetic-reviewed-fence",
            self.private / "operator/export/recovery.dsn": self.role_dsn,
        }
        self.reads = []

    def read(self, path, maximum=8192):
        self.reads.append((path, maximum))
        raw = self.inputs[path]
        self.assertLessEqual(len(raw), maximum)
        return raw

    @contextmanager
    def file_model(self):
        with (
            patch.object(operator_files, "read", self.read),
            patch.object(operator_files, "write_once", resources.put),
        ):
            yield

    def test_profile_binds_all_inputs_and_never_copies_authority_keys(self):
        with self.file_model():
            pin = self.fixture.prepare_recovery(HEAD, CODE)
        root = self.private / "operator/recovery"
        public_raw = (root / "verification.json").read_bytes()
        self.assertEqual(json.loads(public_raw), PUBLIC)
        profile_raw = (self.private / "operator/recovery.json").read_bytes()
        self.assertEqual(pin, hashlib.sha256(profile_raw).hexdigest())
        self.assertEqual(
            json.loads(profile_raw),
            {
                "schemaVersion": 1,
                "runtime_image": resources.IMAGE,
                "source_sha256": SOURCE,
                "code_manifest_sha256": CODE,
                "plan_sha256": hashlib.sha256(b"synthetic-plan").hexdigest(),
                "fence_sha256": hashlib.sha256(b"synthetic-reviewed-fence").hexdigest(),
                "verification_sha256": hashlib.sha256(public_raw).hexdigest(),
            },
        )
        self.assertEqual(
            set(path.name for path in root.iterdir()),
            {
                "verification.json",
                "app.dsn",
                "recovery.dsn",
                "checkpoints.bin",
                "mail-worker.lock",
            },
        )
        self.assertEqual((root / "recovery.dsn").read_bytes(), self.role_dsn)
        self.assertIn(b"user=aqua_app_runtime ", (root / "app.dsn").read_bytes())
        self.assertEqual(len(self.reads), 3)
        self.assertTrue(
            all(
                path.name not in {"identity.key", "signing.key"}
                for path, _ in self.reads
            )
        )
        self.assertTrue(
            all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir())
        )

    def test_create_only_profile_cannot_overwrite_or_extend_expiry(self):
        with self.file_model():
            self.fixture.prepare_recovery(HEAD, CODE)
            before = (self.private / "operator/recovery.json").read_bytes()
            with self.assertRaises(FileExistsError):
                self.fixture.prepare_recovery(HEAD, CODE)
        self.assertEqual((self.private / "operator/recovery.json").read_bytes(), before)

    def test_stale_or_accepted_head_is_not_genesis_profile(self):
        for head in (
            {**HEAD, "sequence": 1},
            {**HEAD, "sequence": False},
            {**HEAD, "source_sha256": "0" * 64},
            {**HEAD, "event_digest": "1" * 64},
        ):
            with (
                self.subTest(head=head),
                self.file_model(),
                self.assertRaises(RuntimeError),
            ):
                self.fixture.prepare_recovery(head, CODE)
        self.assertFalse((self.private / "operator/recovery").exists())

    def test_foreign_or_overprivileged_DSN_is_rejected_before_write(self):
        for role in (b"aqua_retirement_writer", b"postgres"):
            self.inputs[self.private / "operator/export/recovery.dsn"] = (
                self.role_dsn.replace(b"aqua_retirement_recovery", role)
            )
            with (
                self.subTest(role=role),
                self.file_model(),
                self.assertRaises(RuntimeError),
            ):
                self.fixture.prepare_recovery(HEAD, CODE)
        self.assertFalse((self.private / "operator/recovery").exists())


class ChildOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.fixture = object.__new__(resources.Rehearsal)
        self.fixture.run, self.fixture.image = RUN, resources.IMAGE
        self.fixture.pg_image = "sha256:" + "1" * 64
        self.fixture.scope = SimpleNamespace(
            private=Path("/srv/bank-ai/.check-results") / RUN / "installed",
            mail=Path("/srv/bank-ai/.check-results") / RUN / "mail",
            socket=RUN + "-socket",
        )
        self.fixture.child_ids = {}
        self.identifier = "2" * 64
        self.operation = "aqua-retirement-recovery-" + "3" * 32
        mounts = self.fixture.child_mount_sets("recovery")[0]
        self.mounts = [
            {
                "Type": kind,
                "Name" if kind == "volume" else "Source": source,
                "Destination": destination,
                "RW": writable,
            }
            for kind, source, destination, writable in mounts
        ]
        self.labels = {
            "io.aqua.qa-run": RUN,
            "io.aqua.run": self.operation,
            "io.aqua.purpose": "retirement-offline-recovery",
        }

    def identity(self, name=None, labels=None, image=None, mounts=None):
        self.fixture.inspect = Mock(
            return_value=(
                self.identifier,
                name or "/" + self.operation + "-recovery",
                labels or self.labels,
                image or self.fixture.image,
                mounts if mounts is not None else self.mounts,
            )
        )
        return self.fixture.child_identity(self.identifier)

    def test_exact_recovery_child_is_owned_with_four_readonly_mounts(self):
        self.assertEqual(len(self.mounts), 4)
        self.assertTrue(all(item["RW"] is False for item in self.mounts))
        self.assertEqual(self.identity()[0], self.identifier)

    def test_family_or_role_crossovers_are_foreign(self):
        for name in (
            "/aqua-retirement-install-" + "3" * 32 + "-recovery",
            "/" + self.operation + "-peer",
        ):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                self.identity(name=name)

    def test_foreign_label_image_production_mount_or_writable_mount_is_rejected(self):
        variants = [
            {"labels": {**self.labels, "io.aqua.qa-run": "other"}},
            {"image": "sha256:" + "4" * 64},
            {"mounts": [*self.mounts[:-1], {**self.mounts[-1], "RW": True}]},
            {
                "mounts": [
                    (
                        {**item, "Source": "/home/ben2004/.aqua-runtime/retirement"}
                        if item["Type"] == "bind"
                        else item
                    )
                    for item in self.mounts
                ]
            },
        ]
        for changes in variants:
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.identity(**changes)


class CleanLaunchTests(unittest.TestCase):
    def test_direct_clean_import_uses_only_explicit_reviewed_root(self):
        # Stop immediately after actual Rehearsal.__init__ has imported ops.
        # Preparation, Docker calls and private reads are never reached.
        code = r"""
import importlib.util,os,pathlib,sys
path=pathlib.Path(sys.argv[1]);root=path.parents[2]
sys.path=[str(path.parent)]+[p for p in sys.path if p and pathlib.Path(p).resolve()!=root]
if importlib.util.find_spec('ops') is not None:raise RuntimeError('ambient_ops_imported')
spec=importlib.util.spec_from_file_location('clean_controller',path)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
from retirement_fixture import installer_rehearsal_resources as r
original=r.Rehearsal.__init__
def checked(self,*args):
 original(self,*args)
 if pathlib.Path(sys.modules['ops.retirement.operator_scope'].__file__).parents[2]!=root:raise RuntimeError('foreign_ops')
 raise RuntimeError('clean_launch_import_passed')
r.Rehearsal.__init__=checked
m.sys.platform='linux';m.os.geteuid=lambda:1000
try:m.execute(root,'aqua-retirement-host-'+'a'*24,m.IMAGE,'b'*64)
except RuntimeError as e:
 if e.args!=('clean_launch_import_passed',):raise
 print('clean_launch_import_passed')
else:raise RuntimeError('preparation_reached')
"""
        with tempfile.TemporaryDirectory() as cwd:
            result = subprocess.run(
                [
                    sys.executable,
                    "-E",
                    "-s",
                    "-B",
                    "-c",
                    code,
                    str(ROOT / "tools/checks/run_retirement_installer_rehearsal.py"),
                ],
                cwd=cwd,
                env={"PATH": "/usr/bin:/bin"},
                capture_output=True,
                timeout=10,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout, b"clean_launch_import_passed\n")


class ControllerOrderingTests(unittest.TestCase):
    def exercise(self, result):
        events = []
        fixture = Mock()
        fixture.stage = Path("/synthetic/stage")
        fixture.deadline = controller.time.monotonic() + 300
        fixture.prepare.return_value = {
            "source_sha256": SOURCE,
            "install_profile_sha256": "5" * 64,
            "code_manifest_sha256": CODE,
            "child_ownership_linked": True,
        }
        fixture.probe_denials.return_value = {
            "wrong_password_rejected": True,
            "app_role_authority_denied": True,
        }
        fixture.prepare_recovery.side_effect = (
            lambda *args: events.append("profile") or "6" * 64
        )
        fixture.cleanup.return_value = {"complete": True}
        receipt = {
            "status": "installed_writers_still_stopped",
            "maintenance_held": True,
            "writers_resumed": False,
            "cron_resumed": False,
            "initial_encrypted_retention_proven": False,
            "schema9_fallback_proven": False,
            "total_host_restore_supported": False,
            "export_profile_sha256": "7" * 64,
        }
        keeper = Mock()
        keeper.poll.return_value = None
        keeper.stdin.fileno.return_value = 123
        child = Mock()

        def started(stage, run, script, args, children):
            events.append(script)
            children.append(keeper if script == "install.py" else child)
            if script == "recover.py":
                self.assertEqual(args[-2:], ["--protected-sha256", CHAIN])
            return keeper if script == "install.py" else child

        def read(process, limit, until, first_line=False):
            if first_line:
                return io.BytesIO(json.dumps(receipt).encode())
            if process is keeper:
                events.append("keeper_final")
                return io.BytesIO(
                    json.dumps(
                        {k: v for k, v in receipt.items() if k != "maintenance_held"}
                    ).encode()
                )
            return io.BytesIO(json.dumps(result).encode())

        with (
            patch.object(controller.sys, "platform", "linux"),
            patch.object(controller.os, "geteuid", return_value=1000),
            patch.object(resources, "Rehearsal", return_value=fixture),
            patch.object(controller, "start", side_effect=started),
            patch.object(controller, "receive", side_effect=read),
            patch.object(
                controller, "command", side_effect=lambda *args: io.BytesIO(b"{}")
            ),
            patch.object(controller, "checked_head", return_value=HEAD),
            patch.object(controller, "checked_archive", return_value={"modeled": True}),
            patch.object(
                controller.os,
                "write",
                side_effect=lambda *args: events.append("release") or 8,
            ),
            patch.object(controller, "stop", return_value=True),
            patch("builtins.print") as output,
        ):
            rc = controller.execute(ROOT, RUN, resources.IMAGE, SOURCE)
        fixture.cleanup.assert_called_once()
        report = json.loads(output.call_args.args[0])
        return events, rc, report

    def test_actual_CLI_dispatch_follows_keeper_release_and_final_receipt(self):
        events, rc, report = self.exercise(recovery())
        self.assertEqual(
            events, ["install.py", "release", "keeper_final", "profile", "recover.py"]
        )
        self.assertEqual(rc, 0)
        self.assertTrue(report["cleanup"])
        self.assertEqual(report["genesis_recovery_cli"], recovery())

    def test_unready_recovery_stays_red_and_still_cleans_exact_fixture(self):
        events, rc, report = self.exercise(recovery(ready=False))
        self.assertEqual(rc, 1)
        self.assertTrue(report["cleanup"])
        self.assertEqual(report["status"], "failed")
        self.assertNotIn("genesis_recovery_cli", report)


if __name__ == "__main__":
    unittest.main()
