"""Source/lock coherence for the separately qualified native runtime profile."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch

import prepare_retirement_stage as stage
import retirement_normal_image as normal
import run_retirement_installer_rehearsal as installer
from retirement_fixture import installer_rehearsal_resources as resources

ROOT = Path(__file__).resolve().parents[2]
SHARED_PYTHON = {
    "eval/__init__.py",
    "eval/banking/__init__.py",
    "eval/banking/catalog.py",
    "eval/banking/data.py",
    "eval/banking/knowledge.py",
    "eval/banking/proposals.py",
    "eval/banking/reports.py",
    "eval/banking/scope.py",
    "mcp_demo/__init__.py",
    "mcp_demo/data.py",
    "mcp_demo/finance.py",
    "mcp_demo/guidance.py",
    "mcp_demo/protocol.py",
    "mcp_demo/reports.py",
    "mcp_demo/web.py",
}
SHARED_ASSETS = {"mcp_demo/fixtures/bank.json"}


class RuntimePins(unittest.TestCase):
    def test_security_lock_patch_cannot_leave_a_stale_rehearsal_lock(self):
        raw = (ROOT / "tools/checks/requirements-runtime.lock").read_bytes()
        self.assertEqual(len(raw), resources.LOCK_BYTES)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), resources.LOCK_SHA256)

    def test_all_native_qualifiers_agree_on_image_and_inventory(self):
        self.assertEqual(normal.IMAGE, installer.IMAGE)
        self.assertEqual(normal.IMAGE, resources.IMAGE)
        self.assertEqual(normal.MANIFEST_SHA256, resources.RUNTIME_MANIFEST_SHA256)

    def test_compiled_catalog_exactly_matches_reviewed_public_source(self):
        names = {"main.py"} | SHARED_PYTHON
        for directory in (
            "account",
            "analysis",
            "companion",
            "bank_demo",
            "result_companion",
            "context_notes",
            "auth",
            "nl2sql",
            "storage",
            "workspace",
            "preferences",
            "privacy",
            "retirement",
            "migrations",
        ):
            for path in (ROOT / "backend" / directory).rglob("*"):
                if path.suffix in {".py", ".sql"}:
                    names.add(path.relative_to(ROOT / "backend").as_posix())
        self.assertEqual(names, set(normal.RUNTIME_FILES))
        manifest = {}
        for name in sorted(names | resources.ASSETS):
            path = (
                ROOT / name
                if name in SHARED_PYTHON | SHARED_ASSETS
                else ROOT / "backend" / name
            )
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            manifest[name] = {"sha256": digest, "bytes": len(raw)}
            if name in normal.RUNTIME_FILES:
                self.assertEqual(digest, normal.RUNTIME_FILES[name], name)
        self.assertEqual(len(names), 244)
        self.assertEqual(len(manifest), 248)
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(digest, resources.APP_MANIFEST_SHA256)


class SchemaTransition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = stage.full_source(ROOT)
        cls.pin = hashlib.sha256(cls.archive).hexdigest()

    def test_planned_transition_matches_exact_migrations_and_stays_pending(self):
        result = stage.check_schema_transition(
            self.archive, self.pin, normal.IMAGE, 8, 10
        )
        self.assertEqual(result["status"], "source_schema_compatible")
        self.assertIs(result["release_eligible"], False)
        self.assertEqual(result["source_sha256"], self.pin)
        self.assertEqual(result["profiled_backend_image"], normal.IMAGE)
        self.assertEqual(
            result["migrations_to_apply"],
            {
                name: normal.RUNTIME_FILES[name]
                for name in (
                    "migrations/0009_retirement_deletion.sql",
                    "migrations/0010_context_notes.sql",
                )
            },
        )

    def test_schema9_plan_wrong_image_and_unbound_archive_all_deny(self):
        for before, after, image, pin, reason in [
            (8, 9, normal.IMAGE, self.pin, "plan_requires_8_to_10"),
            (9, 10, normal.IMAGE, self.pin, "plan_requires_8_to_10"),
            (8, 10, "sha256:" + "0" * 64, self.pin, "image_profile_mismatch"),
            (8, 10, normal.IMAGE, "0" * 64, "source_pin_changed"),
        ]:
            with (
                self.subTest(reason=reason),
                self.assertRaisesRegex((ValueError, RuntimeError), reason),
            ):
                stage.check_schema_transition(self.archive, pin, image, before, after)

    def test_changed_source_cannot_be_substituted_by_rehashing_the_archive(self):
        names = [
            "backend/" + name
            for name in normal.RUNTIME_FILES
            if name.startswith("migrations/")
        ]
        names.extend(["backend/storage/pool.py", "backend/storage/migrate.py"])
        cached = stage.checked_archive(self.archive, self.pin)
        for changed in [
            "backend/migrations/0008_exports.sql",
            "backend/migrations/0010_context_notes.sql",
            "backend/storage/pool.py",
            "backend/storage/migrate.py",
            "backend/migrations/0011_other.sql",
        ]:
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as archive:
                for name in sorted(set(names) | {changed}):
                    raw = cached.get(name, b"") + (b"\n" if name == changed else b"")
                    member = tarfile.TarInfo(name)
                    member.size = len(raw)
                    archive.addfile(member, io.BytesIO(raw))
            raw = stream.getvalue()
            with (
                self.subTest(changed=changed),
                self.assertRaisesRegex(
                    ValueError, "inventory_mismatch|image_source_mismatch"
                ),
            ):
                stage.check_schema_transition(
                    raw, hashlib.sha256(raw).hexdigest(), normal.IMAGE, 8, 10
                )

    def test_default_plan_remains_io_free_and_check_cannot_select_stage_writes(self):
        with (
            patch.object(stage, "full_source", side_effect=AssertionError),
            patch.object(stage, "stage", side_effect=AssertionError),
        ):
            with (
                patch("sys.argv", ["prepare_retirement_stage.py"]),
                patch("sys.stdout", new_callable=io.StringIO) as output,
            ):
                stage.main()
                self.assertEqual(
                    json.loads(output.getvalue()),
                    {
                        "status": "prepared_only",
                        "private_reads": 0,
                        "writes": 0,
                        "Docker_actions": 0,
                    },
                )
            with (
                patch(
                    "sys.argv",
                    [
                        "stage",
                        "--prepare-stage",
                        "--check-schema-transition",
                        "8",
                        "10",
                    ],
                ),
                patch("sys.stderr", new_callable=io.StringIO),
                self.assertRaises(SystemExit),
            ):
                stage.main()


if __name__ == "__main__":
    unittest.main()
