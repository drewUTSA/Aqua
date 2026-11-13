"""One-way APPEND provisioning for a new installation, never flag removal.

The reviewed controller must prove initializer exit before invoking this
separate process. This process opens only a read descriptor and starts no signer.
"""

import argparse
import array
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

DIRECTORY = Path("/run/aqua-retirement-provisioning")
GETFLAGS = 0x80086601
SETFLAGS = 0x40086602
APPEND = 0x20
IMMUTABLE = 0x10
CAPABILITIES = (1 << 1) | (1 << 3) | (1 << 9)


def provision(device: int, inode: int, genesis_sha256: str) -> dict:
    """Set only APPEND on one exact208-byte newly created, signed-genesis inode."""
    if (
        sys.platform != "linux"
        or os.geteuid() != 0
        or any(
            type(value) is not int or not 0 < value < 2**64 for value in (device, inode)
        )
        or not re.fullmatch(r"[a-f0-9]{64}", genesis_sha256)
    ):
        raise RuntimeError("retirement_append_provision_context_invalid")
    caps = next(
        line.split(":", 1)[1]
        for line in Path("/proc/self/status").read_text().splitlines()
        if line.startswith("CapEff:")
    )
    if int(caps.strip(), 16) != CAPABILITIES:
        raise RuntimeError("retirement_append_provision_capabilities_invalid")
    parent = DIRECTORY.lstat()
    if (
        DIRECTORY.resolve(strict=True) != DIRECTORY
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != 1000
        or stat.S_IMODE(parent.st_mode) != 0o700
        or sorted(path.name for path in DIRECTORY.iterdir()) != ["checkpoints.bin"]
    ):
        raise RuntimeError("retirement_append_provision_directory_invalid")
    path = DIRECTORY / "checkpoints.bin"
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 1000
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size != 208
            or (before.st_dev, before.st_ino) != (device, inode)
            or hashlib.sha256(os.read(fd, 209)).hexdigest() != genesis_sha256
        ):
            raise RuntimeError("retirement_append_provision_genesis_invalid")
        flags = array.array("L", [0])
        fcntl.ioctl(fd, GETFLAGS, flags, True)
        if flags[0] & (APPEND | IMMUTABLE):
            raise RuntimeError("retirement_append_provision_existing_flag_rejected")
        flags[0] |= APPEND
        fcntl.ioctl(fd, SETFLAGS, flags, True)
        os.fsync(fd)
        actual = array.array("L", [0])
        fcntl.ioctl(fd, GETFLAGS, actual, True)
        named, after, current_parent = path.lstat(), os.fstat(fd), DIRECTORY.lstat()
        if (
            actual[0] != flags[0]
            or (named.st_dev, named.st_ino, named.st_size) != (device, inode, 208)
            or (after.st_dev, after.st_ino, after.st_size) != (device, inode, 208)
            or (current_parent.st_dev, current_parent.st_ino)
            != (parent.st_dev, parent.st_ino)
            or path.resolve(strict=True) != path
        ):
            raise RuntimeError("retirement_append_provision_readback_invalid")
    finally:
        os.close(fd)
    return {
        "status": "append_provisioned",
        "device": device,
        "inode": inode,
        "genesis_sha256": genesis_sha256,
        "signer_admitted": False,
        "setter_exit_required_before_signer": True,
        "flag_removal_supported": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--device", type=int)
    parser.add_argument("--inode", type=int)
    parser.add_argument("--genesis-sha256", default="")
    arguments = parser.parse_args()
    if not arguments.execute:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "writes": 0,
                    "private_reads": 0,
                    "flag_removal_supported": False,
                },
                sort_keys=True,
            )
        )
        return
    print(
        json.dumps(
            provision(arguments.device, arguments.inode, arguments.genesis_sha256),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
