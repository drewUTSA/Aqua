"""Regression cases for the portable MCP builder and setup boundary."""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.bank_demo import build_offline_demo as builder
from tools.bank_demo.offline import setup_demo


class PortableBankDemoTests(unittest.TestCase):
    def test_both_dependency_locks_accept_only_hash_pinned_wheels(self):
        for name in builder.LOCKS:
            requirements = builder.requirements((builder.ROOT / name).read_bytes())
            self.assertTrue(requirements)
            self.assertTrue(all(pins for _, _, pins in requirements))
        with self.assertRaises(ValueError):
            builder.requirements(b"demo==1.0\n")
        with self.assertRaises(ValueError):
            builder.requirements(b"--extra-index-url https://example.invalid\n")

    def test_rejects_a_published_wheel_with_different_bytes(self):
        pin = sha256(b"locked").hexdigest()
        entry = {
            "digests": {"sha256": pin},
            "filename": "fictional-1-py3-none-any.whl",
            "packagetype": "bdist_wheel",
            "yanked": False,
            "size": 6,
            "url": "https://files.pythonhosted.org/fictional.whl",
        }
        with patch.object(
            builder,
            "download",
            side_effect=[json.dumps({"urls": [entry]}).encode(), b"change"],
        ):
            with self.assertRaisesRegex(ValueError, "did not match"):
                builder.wheels(("fictional", "1", {pin}))

    def test_setup_rejects_extra_importable_files_and_changed_members(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            name = "serve_demo.py"
            (root / name).write_bytes(b"# demo")
            (root / "MANIFEST.json").write_text(
                json.dumps(
                    {
                        "source": "synthetic",
                        "members": {name: sha256(b"# demo").hexdigest()},
                    }
                )
            )
            with (
                patch.object(setup_demo, "ROOT", root),
                patch.object(setup_demo, "ENV", root / ".aqua-demo-venv"),
            ):
                self.assertEqual(setup_demo.verify()["source"], "synthetic")
                unexpected = root / "unexpected.py"
                unexpected.write_bytes(b"")
                with self.assertRaisesRegex(ValueError, "dedicated folder"):
                    setup_demo.verify()
                unexpected.unlink()
                (root / name).write_bytes(b"# changed")
                with self.assertRaisesRegex(ValueError, "File verification failed"):
                    setup_demo.verify()
