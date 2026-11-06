"""Operator preparation and one-way flag guards, with no actual privileged I/O."""

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ops.retirement import append_provision as provision


class ProvisioningGuards(unittest.TestCase):
    def test_default_commands_read_no_inputs_and_cannot_clear_flags(self):
        root = Path(__file__).resolve().parents[2]
        for name in ("initialize.py", "append_provision.py"):
            result = subprocess.run(
                [sys.executable, str(root / "ops/retirement" / name)],
                capture_output=True,
                timeout=5,
                check=True,
            )
            value = json.loads(result.stdout)
            self.assertEqual(
                (value["status"], value["private_reads"], value["writes"]),
                ("prepared_only", 0, 0),
            )
        result = subprocess.run(
            [
                sys.executable,
                str(root / "ops/retirement/append_provision.py"),
                "--clear",
            ],
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 2)

    def exercise(
        self,
        *,
        change=None,
        existing_flags=0x80000,
        capabilities=provision.CAPABILITIES,
        bad_readback=False,
    ):
        data = b"public synthetic genesis".ljust(208, b"0")
        parent = SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o700, st_uid=1000, st_dev=11, st_ino=12
        )
        current = SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600,
            st_uid=1000,
            st_nlink=1,
            st_size=208,
            st_dev=21,
            st_ino=22,
        )
        if change:
            current = SimpleNamespace(**(vars(current) | change))

        class Node:
            name = "checkpoints.bin"

            def __init__(self, directory=False):
                self.directory = directory

            def resolve(self, strict=True):
                return self

            def lstat(self):
                return parent if self.directory else current

            def iterdir(self):
                return iter([leaf])

            def __truediv__(self, name):
                assert name == "checkpoints.bin"
                return leaf

        leaf, directory = Node(), Node(True)
        flags = {"value": existing_flags, "writes": 0}

        def ioctl(fd, operation, value, mutate):
            self.assertEqual(fd, 77)
            if operation == provision.GETFLAGS:
                value[0] = (
                    flags["value"] & ~provision.APPEND
                    if bad_readback and flags["writes"]
                    else flags["value"]
                )
            else:
                self.assertEqual(operation, provision.SETFLAGS)
                self.assertEqual(value[0], existing_flags | provision.APPEND)
                flags["writes"] += 1
                flags["value"] = value[0]

        with ExitStack() as stack:
            for target, name, value in (
                (provision, "DIRECTORY", directory),
                (provision.sys, "platform", "linux"),
            ):
                stack.enter_context(patch.object(target, name, value))
            stack.enter_context(patch.object(provision.os, "geteuid", return_value=0))
            stack.enter_context(
                patch.object(
                    provision.Path,
                    "read_text",
                    return_value="CapEff:\t" + format(capabilities, "x"),
                )
            )
            opened = stack.enter_context(
                patch.object(provision.os, "open", return_value=77)
            )
            stack.enter_context(
                patch.object(provision.os, "fstat", return_value=current)
            )
            stack.enter_context(patch.object(provision.os, "read", return_value=data))
            stack.enter_context(patch.object(provision.os, "fsync"))
            closed = stack.enter_context(patch.object(provision.os, "close"))
            stack.enter_context(
                patch.object(provision.fcntl, "ioctl", side_effect=ioctl)
            )
            try:
                result = provision.provision(21, 22, hashlib.sha256(data).hexdigest())
                return result, flags
            finally:
                if opened.called:
                    access = opened.call_args.args[1]
                    self.assertEqual(
                        access
                        & (
                            provision.os.O_WRONLY
                            | provision.os.O_RDWR
                            | provision.os.O_CREAT
                            | provision.os.O_TRUNC
                        ),
                        0,
                    )
                    closed.assert_called_once_with(77)

    def test_flag_is_one_way_readonly_descriptor_and_preserves_other_inode_flags(self):
        result, flags = self.exercise()
        self.assertEqual(flags, {"value": 0x80000 | provision.APPEND, "writes": 1})
        self.assertFalse(result["flag_removal_supported"])
        self.assertFalse(result["signer_admitted"])
        self.assertTrue(result["setter_exit_required_before_signer"])

    def test_existing_flag_hardlink_changed_inode_and_wrong_owner_are_rejected(self):
        for changed in (
            {"st_nlink": 2},
            {"st_ino": 23},
            {"st_size": 416},
            {"st_uid": 0},
            {"st_mode": stat.S_IFREG | 0o644},
        ):
            with self.subTest(change=changed), self.assertRaises(RuntimeError):
                self.exercise(change=changed)
        for flags in (provision.APPEND, provision.IMMUTABLE):
            with self.subTest(flags=flags), self.assertRaises(RuntimeError):
                self.exercise(existing_flags=flags)

    def test_excess_missing_capability_or_unconfirmed_readback_never_admit_signer(self):
        for capabilities in (0, provision.CAPABILITIES | (1 << 21)):
            with (
                self.subTest(capabilities=capabilities),
                self.assertRaises(RuntimeError),
            ):
                self.exercise(capabilities=capabilities)
        with self.assertRaises(RuntimeError):
            self.exercise(bad_readback=True)


if __name__ == "__main__":
    unittest.main()
