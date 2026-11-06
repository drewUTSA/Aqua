"""Offline install ordering checks using public directories and fake directory I/O.

Only three function ASTs are compiled. No ops module or supplied top-level code
is imported. No Docker, database, keys, actual directory fsync or crash is used.
"""

import ast
import hashlib
import json
import math
import re
import stat
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[2] / "ops/retirement/install.py"
SOURCE_SHA256 = "4eca10e663c77639e9c92d4fe85df2dd45179041331b80a41f46a45a16226ae3"
PUBLIC_BASE = Path(tempfile.gettempdir()).resolve()
PUBLISHER_FILES = (
    "host-sources/retirement_host.py",
    "backend-sources/retirement/checkpoint.py",
    "backend-sources/retirement/fingerprints.py",
    "backend-sources/retirement/interlock.py",
    "backend-sources/retirement/publisher.py",
)
EXPORT_FILES = (
    "operator_deadline.py",
    "archive.py",
    "backup_protocol.py",
    "export_peer.py",
)


def load_functions(namespace: dict) -> None:
    """Exclude imports and all other module-level executable code."""
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("fsync_regression_source_pin_changed")
    tree = ast.parse(raw)
    names = {"sync_directory", "copy_code", "execute"}
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    if {node.name for node in selected} != names or len(selected) != 3:
        raise RuntimeError("fsync_regression_source_shape")
    exec(  # noqa: S102 - Reviewed function ASTs with controlled fixture globals.
        compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"),
        namespace,
    )


class DirectoryIO:
    """Fake directory descriptors while actual public fixture names stay local."""

    O_RDONLY, O_DIRECTORY, O_NOFOLLOW, O_CLOEXEC = 0, 1, 2, 4

    def __init__(self, root: Path, events: list, *, fail_sync: str | None = None):
        self.root, self.events, self.fail_sync = root, events, fail_sync
        self.opened, self.closed = {}, []
        self.change = {}

    def label(self, path: Path) -> str:
        return "." if path == self.root else path.relative_to(self.root).as_posix()

    def directory(self, path: Path) -> None:
        if (
            path.resolve() != path
            or not path.is_dir()
            or not path.is_relative_to(self.root)
        ):
            raise RuntimeError("public_fixture_directory_invalid")
        self.events.append("verify:" + self.label(path))

    def open(self, path: Path, flags: int) -> int:
        if flags != self.O_DIRECTORY | self.O_NOFOLLOW | self.O_CLOEXEC:
            raise RuntimeError("directory_open_flags_changed")
        self.directory(path)
        fd = 100 + len(self.opened)
        self.opened[fd] = path
        self.events.append("open:" + self.label(path))
        return fd

    def fstat(self, fd: int) -> SimpleNamespace:
        named = self.opened[fd].lstat()
        return SimpleNamespace(
            **{
                "st_uid": 1000,
                "st_mode": stat.S_IFDIR | 0o700,
                "st_dev": named.st_dev,
                "st_ino": named.st_ino,
                **self.change,
            }
        )

    def fsync(self, fd: int) -> None:
        label = self.label(self.opened[fd])
        self.events.append("fsync:" + label)
        if label == self.fail_sync:
            raise OSError("synthetic_fsync_failure")

    def close(self, fd: int) -> None:
        self.closed.append(fd)
        self.events.append("close:" + self.label(self.opened[fd]))

    def chmod(self, path: Path, mode: int) -> None:
        if mode != 0o700 or not path.is_relative_to(self.root):
            raise RuntimeError("public_fixture_chmod_scope")
        self.events.append("chmod:" + self.label(path))


class InstallFsyncTests(unittest.TestCase):
    def fixture(self, stack: ExitStack):
        directory = Path(
            stack.enter_context(
                tempfile.TemporaryDirectory(
                    prefix="aqua-public-fsync-", dir=PUBLIC_BASE
                )
            )
        ).resolve()
        # Validate the exact cleanup target before TemporaryDirectory removes it.
        self.assertEqual(directory.parent, PUBLIC_BASE)
        self.assertTrue(directory.name.startswith("aqua-public-fsync-"))
        return directory

    def namespace(self, root: Path, events: list, io: DirectoryIO) -> dict:
        signal = SimpleNamespace(
            SIGTERM=1,
            SIGINT=2,
            SIGHUP=3,
            SIGALRM=4,
            getsignal=lambda _: None,
            signal=lambda *_: None,
            alarm=lambda _: None,
        )
        namespace = {
            "Path": Path,
            "os": io,
            "stat": stat,
            "directory": io.directory,
            "hashlib": hashlib,
            "json": json,
            "math": math,
            "time": time,
            "re": re,
            "signal": signal,
            "ExitStack": ExitStack,
            # A different unselected root catches accidental production-default
            # use without touching any actual private or production directory.
            "PRIVATE": root / "unselected-production",
            "PRODUCTION": SimpleNamespace(),
            "PUBLISHER_FILES": PUBLISHER_FILES,
            "EXPORT_FILES": EXPORT_FILES,
            "json_bytes": lambda value: json.dumps(value, sort_keys=True).encode(),
        }
        load_functions(namespace)
        return namespace

    def run_install(self, *, fail_sync: str | None = None, existing: bool = False):
        events = []
        with ExitStack() as stack:
            root = self.fixture(stack)
            io = DirectoryIO(root, events, fail_sync=fail_sync)
            namespace = self.namespace(root, events, io)
            private = root / "retirement"
            selected_scope = SimpleNamespace(
                private=private, validate=lambda: events.append("scope_validated")
            )
            if existing:
                private.mkdir()
                (private / "keep.txt").write_bytes(b"PUBLIC EXISTING MARKER")
            spec = {
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
                "runtime_image": spec["runtime_image"],
                "source_sha256": spec["source_sha256"],
            }
            cache = {
                name: b"PUBLIC SOURCE FIXTURE ONLY\n"
                for name in (
                    "materialize.py",
                    "initialize.py",
                    "append_provision.py",
                    "retirement_host.py",
                    *PUBLISHER_FILES,
                    *EXPORT_FILES,
                )
            }

            class Hold:
                def __init__(self, _, *, scope):
                    if scope is not selected_scope:
                        raise RuntimeError("wrong_fixture_hold_scope")
                    self.value = {**spec, "database_id": "9" * 64}
                    self.until = time.monotonic() + 300

                def __enter__(self):
                    events.append("hold_enter")
                    return self

                def __exit__(self, *_):
                    events.append("hold_exit")

                def require(self, schema):
                    if schema != 9:
                        raise RuntimeError("wrong_fixture_schema")
                    events.append("require9")

                def publisher(self):
                    events.append("publisher_EX")

            class Owner:
                def __init__(self, *_, scope):
                    if scope is not selected_scope:
                        raise RuntimeError("wrong_fixture_owner_scope")
                    events.append("owner_created")

                def command(self, *_):
                    return spec["runtime_image"].encode()

                def once(self, role):
                    events.append(role)
                    if role == "materialize":
                        for name in (
                            "authority",
                            "backend",
                            "host",
                            "initializer",
                            "operator",
                            "operator/public",
                            "operator/export",
                            "operator/code",
                        ):
                            (private / name).mkdir()
                    return public

                def close(self):
                    events.append("owner_closed")

            def write_once(path: Path, raw: bytes):
                if not path.is_relative_to(root):
                    raise RuntimeError("public_fixture_write_scope")
                with path.open("xb") as output:
                    output.write(raw)
                events.append("write:" + io.label(path))

            def profile(_, scope):
                self.assertIs(scope, selected_scope)
                return spec

            def provision_database(*_, root):
                self.assertEqual(root, private)
                events.append("independent_SQL")

            namespace.update(
                profile=profile,
                sources=lambda _: cache,
                maintenance=SimpleNamespace(Hold=Hold),
                sql=lambda *_: b"f\n",
                Installer=Owner,
                ack_program=lambda _: b"PUBLIC PROGRAM",
                provision_database=provision_database,
                read=lambda *_: b"PUBLIC VERIFICATION",
                write_once=write_once,
            )
            error = result = None
            try:
                result = namespace["execute"](
                    "0" * 64,
                    retain=lambda _: events.append("retain"),
                    scope=selected_scope,
                )
            except (RuntimeError, OSError) as caught:
                error = type(caught).__name__
            if existing:
                self.assertEqual(
                    (private / "keep.txt").read_bytes(), b"PUBLIC EXISTING MARKER"
                )
            self.assertEqual(set(io.opened), set(io.closed))
            self.assertFalse(namespace["PRIVATE"].exists())
            return result, error, events

    def test_root_parent_sync_precedes_materialize_and_SQL(self):
        result, error, events = self.run_install()
        self.assertIsNone(error)
        self.assertEqual(result["status"], "installed_writers_still_stopped")
        self.assertLess(events.index("chmod:retirement"), events.index("fsync:."))
        self.assertLess(events.index("fsync:."), events.index("materialize"))
        self.assertLess(events.index("fsync:."), events.index("independent_SQL"))

    def test_code_parent_syncs_precede_initializer_and_success(self):
        result, error, events = self.run_install()
        self.assertIsNone(error)
        labels = ("retirement/code/backend-sources", "retirement/code", "retirement")
        positions = [events.index("fsync:" + label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(
            events.index("write:retirement/code/code-manifest.json"), positions[0]
        )
        self.assertLess(positions[-1], events.index("initializer"))
        self.assertLess(events.index("genesis_ack"), events.index("retain"))
        self.assertFalse(result["writers_resumed"])

    def test_root_sync_failure_stops_before_keys_or_SQL(self):
        result, error, events = self.run_install(fail_sync=".")
        self.assertIsNone(result)
        self.assertEqual(error, "OSError")
        self.assertNotIn("owner_created", events)
        self.assertNotIn("materialize", events)
        self.assertNotIn("independent_SQL", events)
        self.assertNotIn("retain", events)
        self.assertIn("hold_exit", events)

    def test_each_code_sync_failure_cleans_without_initializer_or_receipt(self):
        for label in (
            "retirement/code/backend-sources",
            "retirement/code",
            "retirement",
        ):
            with self.subTest(label=label):
                result, error, events = self.run_install(fail_sync=label)
                self.assertIsNone(result)
                self.assertEqual(error, "OSError")
                self.assertNotIn("initializer", events)
                self.assertNotIn("retain", events)
                self.assertLess(events.index("owner_closed"), events.index("hold_exit"))

    def test_exclusive_creation_preserves_existing_public_root(self):
        result, error, events = self.run_install(existing=True)
        self.assertIsNone(result)
        self.assertEqual(error, "FileExistsError")
        self.assertNotIn("fsync:.", events)
        self.assertNotIn("materialize", events)

    def test_verified_descriptor_rejects_owner_mode_type_and_identity(self):
        with ExitStack() as stack:
            root = self.fixture(stack)
            for changed in (
                {"st_uid": 2000},
                {"st_mode": stat.S_IFDIR | 0o770},
                {"st_mode": stat.S_IFREG | 0o700},
                {"st_ino": -1},
            ):
                with self.subTest(changed=changed):
                    events = []
                    io = DirectoryIO(root, events)
                    io.change = changed
                    namespace = self.namespace(root, events, io)
                    with self.assertRaisesRegex(RuntimeError, "directory_changed"):
                        namespace["sync_directory"](root)
                    self.assertNotIn("fsync:.", events)
                    self.assertEqual(set(io.opened), set(io.closed))

    def test_directory_validation_precedes_open(self):
        with ExitStack() as stack:
            root = self.fixture(stack)
            events = []
            io = DirectoryIO(root, events)
            namespace = self.namespace(root, events, io)
            with self.assertRaisesRegex(
                RuntimeError, "public_fixture_directory_invalid"
            ):
                namespace["sync_directory"](root / "missing")
            self.assertEqual(io.opened, {})


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(InstallFsyncTests)
    identities = [case.id() for case in suite]
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.wasSuccessful() and not result.skipped and result.testsRun == 7
    print(
        json.dumps(
            {
                "status": "passed" if passed else "failed",
                "tests": result.testsRun,
                "failures": len(result.failures),
                "errors": len(result.errors),
                "skips": len(result.skipped),
                "identities": identities,
                "mode": "actual_selected_function_AST_public_temp_dirs_mocked_directory_fsync",
                "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                "actual_directory_fsync_or_crash_tested": False,
                "ops_modules_imported": False,
                "server_Docker_database_key_or_network_calls": 0,
            }
        )
    )
    raise SystemExit(not passed)
