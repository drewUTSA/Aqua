"""Source/lock coherence for the separately qualified native runtime profile."""

import hashlib
import json
from pathlib import Path
import unittest

import retirement_normal_image as normal
import run_retirement_installer_rehearsal as installer
from retirement_fixture import installer_rehearsal_resources as resources

ROOT = Path(__file__).resolve().parents[2]


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
        names = {"main.py"}
        for directory in (
            "account",
            "analysis",
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
            raw = (ROOT / "backend" / name).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            manifest[name] = {"sha256": digest, "bytes": len(raw)}
            if name in normal.RUNTIME_FILES:
                self.assertEqual(digest, normal.RUNTIME_FILES[name], name)
        self.assertEqual(len(manifest), 194)
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(digest, resources.APP_MANIFEST_SHA256)


if __name__ == "__main__":
    unittest.main()
