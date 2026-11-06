"""Concrete create-only/maintenance/export guards, never Docker or real keys."""

from contextlib import ExitStack
import hashlib
import importlib.util
import io
import json
import selectors
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ops.retirement import install, install_resources, maintenance, export_resources
from ops.retirement import export_protocol

ROOT = Path(__file__).resolve().parents[2]


class PreparationTests(unittest.TestCase):
    def test_all_explicit_operators_default_to_no_private_actions(self):
        for name in (
            "install",
            "materialize",
            "maintenance",
            "export",
            "installed_publisher",
            "recover",
        ):
            with self.subTest(name=name):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "ops/retirement" / f"{name}.py")],
                    capture_output=True,
                    timeout=5,
                    check=True,
                )
                value = json.loads(result.stdout)
                self.assertEqual(value["status"], "prepared_only")
                self.assertEqual(value["private_reads"], 0)
                self.assertEqual(value.get("writes", 0), 0)
                self.assertEqual(value.get("keys_created", 0), 0)
                self.assertEqual(value.get("Docker_actions", 0), 0)

    def test_publisher_never_accepts_an_unpinned_runtime(self):
        from ops.retirement.publisher_launcher import launch

        with self.assertRaises(RuntimeError):
            launch(expected="a" * 64, image="latest")


class InstallerProcessTests(unittest.TestCase):
    def fixture(self, root):
        (root / "authority").mkdir()
        raw = b"public synthetic genesis".ljust(208, b"0")
        path = root / "authority/checkpoints.bin"
        path.write_bytes(raw)
        meta = path.stat()
        owner = install_resources.Installer(
            {"runtime_image": "sha256:" + "a" * 64, "source_sha256": "b" * 64},
            {name: b'print("public")' for name in install_resources.Installer.roles},
        )
        record = {
            "device": meta.st_dev,
            "inode": meta.st_ino,
            "genesis_sha256": hashlib.sha256(raw).hexdigest(),
            "initializer_exit_required_before_flag": True,
            "signer_admitted": False,
        }
        events = []

        def command(*args):
            events.append(args)
            if args[:2] == ("container", "create"):
                return b"c" * 64
            if args[:2] == ("container", "start"):
                role = owner.attempted[-1]
                value = (
                    record
                    if role == "initializer"
                    else {
                        **{
                            key: record[key]
                            for key in ("device", "inode", "genesis_sha256")
                        },
                        "status": "append_provisioned",
                        "signer_admitted": False,
                        "setter_exit_required_before_signer": True,
                    }
                )
                return json.dumps(value).encode()
            if args[0] == "inspect":
                return b"false\n0\n"
            raise AssertionError(args)

        return owner, record, events, command

    def test_no_signer_or_setter_before_required_process_absence(self):
        owner = install_resources.Installer({"runtime_image": "sha256:" + "a" * 64}, {})
        with patch.object(owner, "command") as calls:
            for role in ("setter", "genesis_ack"):
                with self.subTest(role=role), self.assertRaises(RuntimeError):
                    owner.create(role)
            calls.assert_not_called()
            self.assertEqual(owner.attempted, [])

    def test_initializer_and_setter_removal_are_required_admission_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owner, record, events, command = self.fixture(root)
            with (
                patch.object(install_resources, "PRIVATE", root),
                patch.object(owner, "command", side_effect=command),
                patch.object(owner, "inspect", return_value="c" * 64),
                patch.object(owner, "remove", return_value=True) as remove,
            ):
                self.assertEqual(owner.once("initializer"), record)
                self.assertTrue(owner.initializer_absent)
                remove.assert_called_once_with("initializer")
                owner.once("setter")
                self.assertTrue(owner.setter_absent)
            creates = [
                entry for entry in events if entry[:2] == ("container", "create")
            ]
            initializer, setter = creates
            self.assertIn("--cap-drop=ALL", initializer)
            self.assertNotIn("--cap-add=LINUX_IMMUTABLE", initializer)
            self.assertIn("--user=1000:1000", initializer)
            self.assertEqual(
                {arg for arg in setter if arg.startswith("--cap-add=")},
                {
                    "--cap-add=DAC_OVERRIDE",
                    "--cap-add=FOWNER",
                    "--cap-add=LINUX_IMMUTABLE",
                },
            )
            self.assertIn("--user=0:0", setter)
            self.assertFalse(any("signing.key" in arg for arg in setter))

    def test_uncertain_initializer_or_setter_removal_keeps_signer_closed(self):
        for role in ("initializer", "setter"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                owner, record, events, command = self.fixture(root)
                if role == "setter":
                    owner.initializer_absent = True
                    owner.genesis = record
                with (
                    patch.object(install_resources, "PRIVATE", root),
                    patch.object(owner, "command", side_effect=command),
                    patch.object(owner, "inspect", return_value="c" * 64),
                    patch.object(owner, "remove", return_value=False),
                ):
                    with self.assertRaisesRegex(RuntimeError, "absence_unconfirmed"):
                        owner.once(role)
                self.assertFalse(owner.setter_absent)
                if role == "initializer":
                    self.assertFalse(owner.initializer_absent)

    def test_start_failure_still_attempts_exact_owned_removal(self):
        owner = install_resources.Installer({"runtime_image": "sha256:" + "a" * 64}, {})
        with (
            patch.object(owner, "create", return_value="c" * 64),
            patch.object(owner, "command", side_effect=RuntimeError("start lost")),
            patch.object(owner, "remove", return_value=True) as removal,
        ):
            with self.assertRaisesRegex(RuntimeError, "start lost"):
                owner.once("initializer")
            removal.assert_called_once_with("initializer")
        self.assertFalse(owner.initializer_absent)


class InstalledControllerTests(unittest.TestCase):
    def run_install(
        self, *, fail_at=None, cleanup_failure=False, pause_at=None, records=None
    ):
        events = []
        value = {
            "runtime_image": "sha256:" + "a" * 64,
            "source_sha256": "b" * 64,
            "plan_sha256": "c" * 64,
            "code_manifest_sha256": "d" * 64,
        }
        public = {
            "schemaVersion": 1,
            "installation_id": "00000000-0000-4000-8000-000000000001",
            "identity_key_id": "00000000-0000-4000-8000-000000000002",
            "key_commitment": "e" * 64,
            "public_key": "f" * 64,
            "runtime_image": value["runtime_image"],
            "source_sha256": value["source_sha256"],
        }

        class Hold:
            def __init__(self, pin, **kwargs):
                self.value = {**value, "database_id": "9" * 64}
                self.until = maintenance.time.monotonic() + 300

            def __enter__(self):
                events.append("hold_enter")
                return self

            def __exit__(self, *args):
                events.append("hold_exit")

            def require(self, schema):
                events.append("require9")

            def publisher(self):
                events.append("publisher_EX")

        class Owner:
            def __init__(self, *args, **kwargs):
                pass

            def command(self, *args):
                return value["runtime_image"].encode()

            def once(self, role):
                events.append(role)
                if role == pause_at:
                    print("OWNED_CHILD_READY", flush=True)
                    signal.pause()
                if role == fail_at:
                    raise RuntimeError("injected_" + role)
                return public

            def close(self):
                events.append("owned_cleanup")
                if cleanup_failure:
                    raise RuntimeError("cleanup_uncertain")

        with ExitStack() as stack:
            stack.enter_context(patch.object(install, "profile", return_value=value))
            stack.enter_context(
                patch.object(
                    install,
                    "sources",
                    return_value={name: b"public" for name in install.SOURCE_NAMES},
                )
            )
            stack.enter_context(patch.object(install.maintenance, "Hold", Hold))
            stack.enter_context(patch.object(install, "sql", return_value=b"f\n"))
            stack.enter_context(patch.object(install, "directory"))
            stack.enter_context(patch.object(install.os, "chmod"))
            stack.enter_context(patch.object(install.Path, "mkdir"))
            stack.enter_context(patch.object(install, "sync_directory"))
            stack.enter_context(patch.object(install, "Installer", Owner))
            stack.enter_context(
                patch.object(
                    install,
                    "provision_database",
                    side_effect=lambda *args, **kwargs: events.append(
                        "independent_SQL"
                    ),
                )
            )
            stack.enter_context(
                patch.object(install, "copy_code", return_value=("1" * 64, "2" * 64))
            )
            stack.enter_context(
                patch.object(install, "read", return_value=b"public verification")
            )

            def write(path, raw):
                if records is not None:
                    records[str(path)] = json.loads(raw)

            stack.enter_context(patch.object(install, "write_once", side_effect=write))
            try:
                result = install.execute(
                    "0" * 64, retain=lambda receipt: events.append("capture_while_held")
                )
                return result, events
            except RuntimeError:
                return None, events

    def test_actual_process_order_and_capture_before_guard_release(self):
        result, events = self.run_install()
        self.assertIsNotNone(result)
        self.assertLess(events.index("publisher_EX"), events.index("initializer"))
        self.assertLess(events.index("initializer"), events.index("setter"))
        self.assertLess(events.index("setter"), events.index("genesis_ack"))
        self.assertLess(
            events.index("owned_cleanup"), events.index("capture_while_held")
        )
        self.assertLess(events.index("capture_while_held"), events.index("hold_exit"))
        for key in (
            "writers_resumed",
            "cron_resumed",
            "initial_encrypted_retention_proven",
            "schema9_fallback_proven",
            "total_host_restore_supported",
        ):
            self.assertIs(result[key], False)

    def test_every_failure_cleans_before_guard_exit_without_next_stage(self):
        for role in ("materialize", "initializer", "setter", "genesis_ack"):
            with self.subTest(role=role):
                result, events = self.run_install(fail_at=role)
                self.assertIsNone(result)
                self.assertLess(
                    events.index("owned_cleanup"), events.index("hold_exit")
                )
                self.assertNotIn("capture_while_held", events)
                if role != "genesis_ack":
                    self.assertNotIn("genesis_ack", events)

    def test_real_SIGTERM_finishes_owned_cleanup_before_guard_release(self):
        code = """import json,sys
sys.path[:0]=sys.argv[1:]
from test_retirement_operator import InstalledControllerTests
result,events=InstalledControllerTests().run_install(pause_at='materialize')
print(json.dumps({'result':result,'events':events,'Docker_actions':0}),flush=True)
"""
        process = subprocess.Popen(
            [
                sys.executable,
                "-E",
                "-s",
                "-B",
                "-c",
                code,
                str(ROOT),
                str(ROOT / "tools/checks"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            self.assertTrue(
                selector.select(5), "own child never reached controlled stage"
            )
            self.assertEqual(process.stdout.readline(), b"OWNED_CHILD_READY\n")
            process.send_signal(signal.SIGTERM)
            output, errors = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, errors.decode())
            value = json.loads(output)
            self.assertIsNone(value["result"])
            self.assertEqual(value["Docker_actions"], 0)
            self.assertLess(
                value["events"].index("owned_cleanup"),
                value["events"].index("hold_exit"),
            )
            self.assertNotIn("capture_while_held", value["events"])
        finally:
            selector.close()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
            process.stdout.close()
            process.stderr.close()

    def test_uncertain_cleanup_cannot_emit_receipt_or_enter_capture(self):
        result, events = self.run_install(cleanup_failure=True)
        self.assertIsNone(result)
        self.assertEqual(events.count("owned_cleanup"), 1)
        self.assertNotIn("capture_while_held", events)
        self.assertLess(events.index("owned_cleanup"), events.index("hold_exit"))


class AbsenceTests(unittest.TestCase):
    def test_missing_requires_exact_no_such_name_and_empty_output(self):
        owner = export_resources.Owned({})
        name = owner.name + "-peer"
        for raw, stderr, accepted in (
            (b"", ("Error: No such container: " + name + "\n").encode(), True),
            (b"[]\n", ("Error: No such object: " + name + "\n").encode(), True),
            (b"\n", ("Error: No such container: " + name + "\n").encode(), True),
            (b"\n\n", ("Error: No such container: " + name + "\n").encode(), False),
            (b"foreign", ("Error: No such container: " + name + "\n").encode(), False),
            (b"", b"daemon unavailable", False),
            (b"", b"Error: No such container: other\n", False),
        ):
            with (
                self.subTest(raw=raw, stderr=stderr),
                patch.object(
                    export_resources.subprocess,
                    "run",
                    return_value=SimpleNamespace(
                        returncode=1, stdout=raw, stderr=stderr
                    ),
                ),
            ):
                if accepted:
                    self.assertIsNone(owner.inspect("peer"))
                else:
                    with self.assertRaises(RuntimeError):
                        owner.inspect("peer")

    def test_newline_absence_still_requires_exact_error_and_status(self):
        owner = export_resources.Owned({})
        name = owner.name + "-peer"
        correct = ("Error: No such container: " + name + "\n").encode()
        for code, error in (
            (0, correct),
            (2, correct),
            (1, b"daemon unavailable"),
            (1, b"Error: No such container: other\n"),
            (1, ("Error: No such container: " + name + "-foreign\n").encode()),
        ):
            with (
                self.subTest(code=code, error=error),
                patch.object(
                    export_resources.subprocess,
                    "run",
                    return_value=SimpleNamespace(
                        returncode=code, stdout=b"\n", stderr=error
                    ),
                ),
                self.assertRaises(RuntimeError),
            ):
                owner.inspect("peer")


class BinaryPipeTests(unittest.TestCase):
    def peer(self, mode):
        # A real owned Python child and OS pipes, no Docker/keys/database.
        source = """import os,struct,sys
mode=sys.argv[1]
os.write(1,b'AUTHORITY_DUMP\\n')
size=struct.unpack('!Q',sys.stdin.buffer.read(8))[0]
raw=sys.stdin.buffer.read(size)
if raw!=b'PGDMP-synthetic':raise SystemExit(2)
payload=b'public tar placeholder\\x00'+bytes(range(256))
header=b'ARCHIVE '+str(len(payload)).encode()+b'\\n'
if mode=='capacity':header=b'ARCHIVE 202375169\\n'
if mode=='badheader':header=b'PRIVATE_KEY payload\\n'
os.write(1,header+payload[:10] if mode=='truncated' else header+payload)
if mode=='trailing':os.write(1,b'EXTRA')
if mode=='nonzero':raise SystemExit(3)
"""
        process = subprocess.Popen(
            [sys.executable, "-E", "-s", "-B", "-c", source, mode],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return process

    def test_only_tar_bytes_reach_encryption_sink(self):
        process = self.peer("valid")
        try:
            output = io.BytesIO()
            receipt = export_protocol.archive(
                export_protocol.Channel(process, time.monotonic() + 5),
                lambda: b"PGDMP-synthetic",
                output,
            )
            expected = b"public tar placeholder\x00" + bytes(range(256))
            self.assertEqual(output.getvalue(), expected)
            self.assertEqual(
                receipt,
                {
                    "plaintext_bytes": len(expected),
                    "plaintext_sha256": hashlib.sha256(expected).hexdigest(),
                },
            )
        finally:
            process.kill() if process.poll() is None else None
            process.wait(timeout=3)
            process.stdin.close()
            process.stdout.close()

    def test_capacity_header_truncation_trailing_and_nonzero_stay_red(self):
        for mode in ("capacity", "badheader", "truncated", "trailing", "nonzero"):
            with self.subTest(mode=mode):
                process = self.peer(mode)
                try:
                    with self.assertRaises(RuntimeError):
                        export_protocol.archive(
                            export_protocol.Channel(process, time.monotonic() + 5),
                            lambda: b"PGDMP-synthetic",
                            io.BytesIO(),
                        )
                finally:
                    process.kill() if process.poll() is None else None
                    process.wait(timeout=3)
                    process.stdin.close()
                    process.stdout.close()

    def test_short_sink_write_is_never_success(self):
        process = self.peer("valid")
        try:
            with self.assertRaisesRegex(RuntimeError, "short_output_write"):
                export_protocol.archive(
                    export_protocol.Channel(process, time.monotonic() + 5),
                    lambda: b"PGDMP-synthetic",
                    SimpleNamespace(write=lambda raw: len(raw) - 1),
                )
        finally:
            process.kill() if process.poll() is None else None
            process.wait(timeout=3)
            process.stdin.close()
            process.stdout.close()


class NormalRuntimeGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "tools/checks/retirement_fixture/normal_runtime_probe.py"
        spec = importlib.util.spec_from_file_location("normal_runtime_qa", path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def inputs(self):
        return {
            "run": "aqua-retirement-host-" + "1" * 24,
            "mode": "ready",
            "runtime_files": {f"module{i}.py": "a" * 64 for i in range(100)},
            "session_token": "v2." + "S" * 43,
            "csrf_token": "C" * 43,
            "receipt_token": "v2." + "R" * 43,
            "intent_id": "00000000-0000-4000-8000-000000000001",
            "job_id": "00000000-0000-4000-8000-000000000002",
            "owner_id": "00000000-0000-4000-8000-000000000003",
        }

    def test_exact_production_topology_argv_without_injection(self):
        from privacy.policy import runtime_context

        self.assertTrue(runtime_context(self.module.ARGV))
        self.assertEqual(self.module.ENV["PRIVATE_DATA_DELETE_ENABLED"], "false")
        self.assertEqual(self.module.ENV["PYTHONPATH"], "/app")
        self.assertFalse(any(name.startswith("PG") for name in self.module.ENV))
        self.assertFalse(
            any(
                "recovery" in value or "signing.key" in value
                for value in self.module.ENV.values()
            )
        )
        value = self.inputs()
        self.assertEqual(self.module.checked(value), value)

    def test_closed_mode_scope_tokens_manifest_and_mass_assignment(self):
        for field, replacement in (
            ("mode", "total_host_restore"),
            ("run", "production"),
            ("receipt_token", "secret"),
            ("runtime_files", {"main.py": "a" * 64}),
            ("owner_id", "unknown"),
        ):
            with (
                self.subTest(field=field),
                self.assertRaises((RuntimeError, ValueError)),
            ):
                self.module.checked({**self.inputs(), field: replacement})
        with self.assertRaises(RuntimeError):
            self.module.checked({**self.inputs(), "recovery_password": "forbidden"})

    def test_exact_compiled_bytes_reject_extra_missing_and_changed_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "main.py"
            path.write_bytes(b"public runtime")
            manifest = {"main.py": hashlib.sha256(path.read_bytes()).hexdigest()}
            self.assertEqual(len(self.module.exact_runtime(manifest, root)), 64)
            for mutate in ("extra", "missing", "changed"):
                with self.subTest(mutate=mutate):
                    path.write_bytes(b"public runtime")
                    extra = root / "extra.sql"
                    if extra.exists():
                        extra.unlink()
                    if mutate == "extra":
                        extra.write_bytes(b"public source")
                    elif mutate == "missing":
                        path.unlink()
                    else:
                        path.write_bytes(b"changed runtime")
                    with self.assertRaises(RuntimeError):
                        self.module.exact_runtime(manifest, root)

    def test_flag_off_request_passes_closed_DTO_before_service_gate(self):
        from privacy.deletion_contracts import DeletionCreate

        for receipt in ("v2." + "P" * 43, "v2." + "Q" * 43, "v2." + "R" * 43):
            with self.subTest(receipt=receipt):
                body = self.module.new_body(receipt)
                validated = DeletionCreate.model_validate(body)
                self.assertNotEqual(validated.proof_token, validated.receipt_token)
                self.assertEqual(validated.receipt_token, receipt)

    def test_default_normal_probe_starts_no_process(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/checks/retirement_fixture/normal_runtime_probe.py"),
            ],
            capture_output=True,
            timeout=5,
            check=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {"status": "prepared_only", "private_reads": 0, "processes_started": 0},
        )


class RecoveryHandoffGuards(unittest.TestCase):
    def holder(self):
        holder = maintenance.Hold("a" * 64)
        holder.fds = [11, 12, 13, 14]
        holder.physical_fd = 13
        holder.publisher_locked = True
        holder.record = {"public": "holder"}
        return holder

    def test_attestation_is_removed_before_only_physical_EX_is_released(self):
        holder = self.holder()
        events = []
        state = SimpleNamespace(unlink=lambda: events.append("attestation_removed"))
        with (
            patch.object(holder, "require"),
            patch.object(maintenance, "STATE", state),
            patch.object(
                maintenance, "read", return_value=maintenance.json_bytes(holder.record)
            ),
            patch.object(
                maintenance.os,
                "close",
                side_effect=lambda fd: events.append(("close", fd)),
            ),
        ):
            holder.recovery_handoff()
        self.assertEqual(events, ["attestation_removed", ("close", 13)])
        self.assertEqual(holder.fds, [11, 12, 14])
        self.assertTrue(holder.recovery_only)

    def test_changed_or_unremovable_attestation_keeps_physical_claim(self):
        for changed in (True, False):
            holder = self.holder()
            state = SimpleNamespace(
                unlink=lambda: (_ for _ in ()).throw(OSError("unlink denied"))
            )
            with (
                self.subTest(changed=changed),
                patch.object(holder, "require"),
                patch.object(maintenance, "STATE", state),
                patch.object(
                    maintenance,
                    "read",
                    return_value=(
                        b"changed" if changed else maintenance.json_bytes(holder.record)
                    ),
                ),
                patch.object(maintenance.os, "close") as close,
            ):
                with self.assertRaises((RuntimeError, OSError)):
                    holder.recovery_handoff()
                close.assert_not_called()
                self.assertEqual(holder.fds, [11, 12, 13, 14])

    def test_no_publisher_claim_or_repeated_handoff_cannot_release_anything(self):
        for repeated in (False, True):
            holder = self.holder()
            holder.publisher_locked = False if not repeated else True
            holder.recovery_only = repeated
            with (
                self.subTest(repeated=repeated),
                patch.object(holder, "require"),
                patch.object(maintenance, "read") as read,
                patch.object(maintenance.os, "close") as close,
            ):
                with self.assertRaises(RuntimeError):
                    holder.recovery_handoff()
                read.assert_not_called()
                close.assert_not_called()

    def test_total_host_recovery_remains_unconditionally_closed(self):
        from ops.retirement.recovery_driver import total_host

        for kwargs in (
            {},
            {"latest_verified": True},
            {"backup_age_seconds": 0, "operator_approved": True},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeError):
                total_host(**kwargs)


class Capture129Guards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "tools/checks/retirement_fixture/capture129.py"
        # Explicit local public fixture-code location, no ambient import path.
        sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location("capture129_qa", path)
        cls.module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(cls.module)
        finally:
            sys.path.remove(str(path.parent))

    def test_explicit_account_original_reaches_128_plus_one_without_omission(self):
        from retirement.pages import INITIAL, page_digest, decode

        key, record, data = self.module.original()
        self.assertEqual(data.count, 129)
        self.assertEqual(tuple(map(len, data.pages)), (128, 1))
        self.assertEqual(record.scope, "account_v1")
        self.assertIs(record.closed, True)
        self.assertEqual(
            (record.history_floor, record.privacy_floor, record.auth_floor), (2, 2, 1)
        )
        self.assertEqual(
            (record.fingerprint_count, record.fingerprint_root), (data.count, data.root)
        )
        previous = INITIAL
        fingerprints = set()
        for ordinal, page in enumerate(data.pages):
            previous = page_digest(previous, ordinal, page)
            for entry in page:
                dataset, fingerprint = decode(entry)
                self.assertEqual((dataset, fingerprint.key_id), ("d" * 64, key.key_id))
                fingerprints.add(fingerprint.digest)
        self.assertEqual((previous, len(fingerprints)), (data.root, 129))

    def test_producer_default_never_opens_database_or_writes_manifest(self):
        env = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(ROOT / "tools/checks/retirement_fixture"),
        }
        result = subprocess.run(
            [
                sys.executable,
                "-s",
                "-B",
                str(ROOT / "tools/checks/retirement_fixture/capture129.py"),
            ],
            env=env,
            capture_output=True,
            timeout=5,
            check=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "status": "prepared_only",
                "private_reads": 0,
                "pool_opens": 0,
                "writes": 0,
            },
        )


class ResourceIdentityGuards(unittest.TestCase):
    def owner(self):
        owner = export_resources.Owned(
            {"runtime_image": "sha256:" + "f" * 64, "code_manifest_sha256": "e" * 64}
        )
        owner.attempted.append("peer")
        owner.uncertain.add("peer")
        return owner

    def metadata(self, owner, identifier="a" * 64):
        raw = b"\n".join(
            json.dumps(item).encode()
            for item in (
                identifier,
                "/" + owner.name + "-peer",
                {"io.aqua.run": owner.name, "io.aqua.purpose": owner.purpose},
                owner.profile["runtime_image"],
            )
        )
        return SimpleNamespace(returncode=0, stdout=raw, stderr=b"")

    def absent(self, owner):
        return SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=("Error: No such container: " + owner.name + "-peer\n").encode(),
        )

    def test_known_renamed_ID_cannot_be_claimed_clean_or_blindly_removed(self):
        owner = export_resources.Owned(
            {"runtime_image": "sha256:" + "f" * 64, "code_manifest_sha256": "e" * 64}
        )
        calls = []

        def command(*args):
            calls.append(args)
            if args[:2] == ("container", "create"):
                return b"a" * 64
            if args[0] == "ps":
                return b"a" * 64 + b"\n"
            raise AssertionError("must not blindly remove renamed ID")

        with (
            patch.object(owner, "inspect", side_effect=["a" * 64, None, None]),
            patch.object(owner, "command", side_effect=command),
        ):
            owner.create("peer")
            self.assertFalse(owner.remove("peer"))
        self.assertEqual(
            calls[-1],
            (
                "ps",
                "--all",
                "--no-trunc",
                "--filter=id=" + "a" * 64,
                "--format={{.ID}}",
            ),
        )

    def test_original_ID_and_exact_name_must_both_be_absent(self):
        owner = self.owner()
        owner.created["peer"] = "a" * 64
        with (
            patch.object(owner, "inspect", return_value=None),
            patch.object(owner, "command", return_value=b"") as calls,
        ):
            self.assertTrue(owner.remove("peer"))
            self.assertNotIn("peer", owner.uncertain)
            calls.assert_called_once()

    def test_unresolved_lost_create_absence_remains_red(self):
        owner = self.owner()
        with (
            patch.object(owner, "inspect", return_value=None),
            patch.object(owner, "command") as calls,
        ):
            self.assertFalse(owner.remove("peer"))
            calls.assert_not_called()
        self.assertIn("peer", owner.uncertain)

    def test_lost_create_can_resolve_only_matching_actual_owned_name(self):
        owner = self.owner()
        with (
            patch.object(
                export_resources.subprocess,
                "run",
                side_effect=[self.metadata(owner), self.absent(owner)],
            ),
            patch.object(owner, "command", return_value=b"") as calls,
        ):
            self.assertTrue(owner.remove("peer"))
            self.assertEqual(owner.created["peer"], "a" * 64)
            self.assertEqual(
                calls.call_args_list[0].args, ("container", "rm", "--force", "a" * 64)
            )
            self.assertEqual(
                calls.call_args_list[1].args,
                (
                    "ps",
                    "--all",
                    "--no-trunc",
                    "--filter=id=" + "a" * 64,
                    "--format={{.ID}}",
                ),
            )

    def test_same_name_labels_but_foreign_ID_cannot_replace_known_object(self):
        owner = self.owner()
        owner.created["peer"] = "a" * 64
        with (
            patch.object(
                export_resources.subprocess,
                "run",
                return_value=self.metadata(owner, "b" * 64),
            ),
            patch.object(owner, "command") as calls,
        ):
            with self.assertRaises(RuntimeError):
                owner.remove("peer")
            calls.assert_not_called()
            self.assertEqual(owner.created["peer"], "a" * 64)

    def test_returned_ID_retained_before_first_inspection_in_every_operator(self):
        from ops.retirement.recover import Recovery

        profile = {
            "runtime_image": "sha256:" + "f" * 64,
            "source_sha256": "e" * 64,
            "code_manifest_sha256": "d" * 64,
        }
        for owner, role in (
            (export_resources.Owned(profile), "peer"),
            (
                install_resources.Installer(profile, {"materialize": b"public"}),
                "materialize",
            ),
            (Recovery(profile, "public"), "recovery"),
        ):

            def inspect(selected):
                self.assertEqual(owner.created[selected], "a" * 64)
                raise RuntimeError("first inspect lost")

            with (
                self.subTest(role=role),
                patch.object(owner, "command", return_value=b"a" * 64),
                patch.object(owner, "inspect", side_effect=inspect),
            ):
                with self.assertRaisesRegex(RuntimeError, "first inspect lost"):
                    owner.create(role)
                self.assertEqual(owner.created[role], "a" * 64)
                self.assertIn(role, owner.uncertain)


class InstalledPublisherRoundtrip(unittest.TestCase):
    def test_actual_generated_profile_reaches_launch_only_after_host_source_pin(self):
        from ops.retirement import installed_publisher

        records = {}
        result, events = InstalledControllerTests().run_install(records=records)
        self.assertIsNotNone(result)
        generated = records[str(install.PRIVATE / "host/publisher.json")]
        self.assertEqual(
            set(generated),
            {
                "schemaVersion",
                "runtime_image",
                "source_sha256",
                "code_manifest_sha256",
                "host_code_manifest_sha256",
            },
        )
        order = []
        with (
            patch.object(installed_publisher, "pinned", return_value=generated),
            patch.object(
                install,
                "sources",
                side_effect=lambda pin: order.append(("source", pin)),
            ),
            patch.object(
                installed_publisher,
                "launch",
                side_effect=lambda *args, **kwargs: order.append(
                    ("launch", args, kwargs)
                )
                or "checked",
            ),
        ):
            self.assertEqual(installed_publisher.execute("a" * 64), "checked")
        self.assertEqual(order[0], ("source", generated["host_code_manifest_sha256"]))
        self.assertEqual(
            order[1],
            (
                "launch",
                (installed_publisher.PRIVATE, generated["code_manifest_sha256"]),
                {"image": generated["runtime_image"]},
            ),
        )

    def test_legacy_missing_pin_and_unknown_fields_are_closed(self):
        from ops.retirement import installed_publisher

        valid = {
            "schemaVersion": 1,
            "runtime_image": "sha256:" + "a" * 64,
            "source_sha256": "b" * 64,
            "code_manifest_sha256": "c" * 64,
            "host_code_manifest_sha256": "d" * 64,
        }
        for profile in (
            {
                key: value
                for key, value in valid.items()
                if key != "host_code_manifest_sha256"
            },
            {**valid, "operator_override": True},
        ):
            with (
                self.subTest(profile=profile),
                patch.object(installed_publisher, "pinned", return_value=profile),
                patch.object(installed_publisher, "launch") as launch,
            ):
                with self.assertRaises(RuntimeError):
                    installed_publisher.execute("a" * 64)
                launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
