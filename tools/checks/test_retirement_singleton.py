"""Actual singleton/maintenance flock conflict on one inode, no Docker or keys."""

from contextlib import ExitStack
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from ops.accountmail.private_env import singleton, private_directory
from ops.retirement import maintenance


class SingletonMappingGuards(unittest.TestCase):
    def test_actual_launcher_inode_is_the_maintenance_inode(self):
        self.assertEqual(
            maintenance.launcher_lock(Path("/owned/mail")).name, ".launcher.lock"
        )
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve() / "mail"
            directory.mkdir(mode=0o700)
            wrong = directory / "worker.lock"
            wrong.touch(mode=0o600)
            original_fstat = os.fstat

            def fstat(fd):
                value = original_fstat(fd)
                return SimpleNamespace(
                    st_mode=value.st_mode,
                    st_uid=1000,
                    st_nlink=value.st_nlink,
                    st_size=value.st_size,
                    st_dev=value.st_dev,
                    st_ino=value.st_ino,
                )

            with singleton(directory) as held:
                self.assertIs(held, True)
                actual = (directory / ".launcher.lock").stat()
                with ExitStack() as adapters:
                    # Linux UID1000 requires no metadata adapters. On this Mac,
                    # preserve actual canonical/private owner checks and map
                    # only the UIDfield for Linux-only maintenance validation.
                    if os.geteuid() != 1000:
                        adapters.enter_context(
                            patch.object(
                                maintenance, "directory", side_effect=private_directory
                            )
                        )
                        adapters.enter_context(
                            patch.object(maintenance.os, "fstat", side_effect=fstat)
                        )
                    wrong_fd = maintenance.lock(wrong)
                    os.close(wrong_fd)  # Concrete old worker.lock counterexample.
                    with self.assertRaises(BlockingIOError):
                        maintenance.lock(maintenance.launcher_lock(directory))
                    self.assertEqual(
                        (actual.st_dev, actual.st_ino),
                        (
                            (directory / ".launcher.lock").stat().st_dev,
                            (directory / ".launcher.lock").stat().st_ino,
                        ),
                    )
            with ExitStack() as adapters:
                if os.geteuid() != 1000:
                    adapters.enter_context(
                        patch.object(
                            maintenance, "directory", side_effect=private_directory
                        )
                    )
                    adapters.enter_context(
                        patch.object(maintenance.os, "fstat", side_effect=fstat)
                    )
                descriptor = maintenance.lock(maintenance.launcher_lock(directory))
                os.close(descriptor)


if __name__ == "__main__":
    unittest.main()
