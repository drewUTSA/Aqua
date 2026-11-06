"""Create-only public operator stage for an explicit owned QA run, no Docker.

The production release uses the same fixed source set in its reviewed stage;
this CLI only writes beneath an already validated fresh QA fixture root.
"""

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
# One reviewed runtime195 data asset exceeds the ordinary public-code cap.
# This exception admits only its approved raw bytes, never another large member.
LARGE_ASSET = "backend/auth/password_blocklist_sha256.txt"
LARGE_ASSET_BYTES = 708370
LARGE_ASSET_SHA256 = "a5b8b74b66c0ed54d90098285cb0dbe02217ae41d7c91f0c57cf4a761e14521a"


def put(path: Path, raw: bytes) -> None:
    fd = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def checked_archive(raw: bytes, expected: str) -> dict[str, bytes]:
    """Cache only bounded regular public members of the exact reviewed source."""
    if len(raw) > 16 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("operator_stage_full_source_pin_changed")
    cache = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for member in archive.getmembers():
            name = PurePosixPath(member.name)
            if (
                not member.isfile()
                or member.name in cache
                or name.is_absolute()
                or name.as_posix() != member.name
                or any(part in {"", ".", ".."} for part in name.parts)
                or "\\" in member.name
                or len(cache) >= 1024
                or not 0
                <= member.size
                <= (LARGE_ASSET_BYTES if member.name == LARGE_ASSET else 262144)
            ):
                raise RuntimeError("operator_stage_source_member_invalid")
            stream = archive.extractfile(member)
            if stream is None:
                raise RuntimeError("operator_stage_source_member_missing")
            cache[member.name] = stream.read(member.size + 1)
            if len(cache[member.name]) != member.size:
                raise RuntimeError("operator_stage_source_member_size")
            if member.name == LARGE_ASSET and (
                member.size != LARGE_ASSET_BYTES
                or hashlib.sha256(cache[member.name]).hexdigest() != LARGE_ASSET_SHA256
            ):
                raise RuntimeError("operator_stage_runtime_asset_changed")
    return cache


def stage(root: Path, output: Path, names, *, cached=None) -> str:
    cache = {}
    for name in names:
        source = (
            root / "backend" / name.removeprefix("backend-sources/")
            if name.startswith("backend-sources/")
            else (
                root / "ops/appdb/restore_session_fence.sql"
                if name == "restore_session_fence.sql"
                else root / "ops/retirement" / name
            )
        )
        if cached is None:
            if source.resolve(strict=True) != source or not source.is_file():
                raise RuntimeError("operator_stage_source_not_regular")
            raw = source.read_bytes()
        else:
            # Read exactly the bytes checked above, not a second mutable checkout.
            raw = cached[source.relative_to(root).as_posix()]
        if not 0 < len(raw) <= 131072:
            raise RuntimeError("operator_stage_source_capacity")
        cache[name] = raw
    output.mkdir(mode=0o700)
    os.chmod(output, 0o700)
    for name, raw in sorted(cache.items()):
        path = output / name
        for parent in reversed(path.parent.parents):
            if (parent == output or output in parent.parents) and not parent.exists():
                parent.mkdir(mode=0o700)
                os.chmod(parent, 0o700)
        if not path.parent.exists():
            path.parent.mkdir(mode=0o700)
            os.chmod(path.parent, 0o700)
        put(path, raw)
    manifest = json.dumps(
        {name: hashlib.sha256(raw).hexdigest() for name, raw in cache.items()},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    put(output / "installation-sources.json", manifest)
    for path in [
        *sorted((item for item in output.rglob("*") if item.is_dir()), reverse=True),
        output,
        output.parent,
    ]:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return hashlib.sha256(manifest).hexdigest()


def full_source(root: Path) -> bytes:
    import run_backend

    run_backend.ROOT = root
    baseline = run_backend.source_archive()
    output = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(baseline), mode="r:") as original,
        tarfile.open(fileobj=output, mode="w") as packed,
    ):
        for member in original.getmembers():
            if member.name == "ops/appdb/pg_hba.conf":
                raise RuntimeError("operator_HBA_packager_duplicate")
            packed.addfile(member, original.extractfile(member))
        path = root / "ops/appdb/pg_hba.conf"
        if path.resolve(strict=True) != path:
            raise RuntimeError("operator_HBA_symlink")
        raw = path.read_bytes()
        if not 0 < len(raw) <= 16384:
            raise RuntimeError("operator_HBA_capacity")
        member = tarfile.TarInfo("ops/appdb/pg_hba.conf")
        member.size = len(raw)
        member.mode = 0o644
        member.uid = member.gid = 1000
        packed.addfile(member, io.BytesIO(raw))
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-stage", action="store_true")
    parser.add_argument("--qa-run")
    parser.add_argument("--source-sha256")
    args = parser.parse_args()
    if not args.prepare_stage:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "private_reads": 0,
                    "writes": 0,
                    "Docker_actions": 0,
                }
            )
        )
        return
    sys.path.insert(0, str(ROOT))
    from ops.retirement.install import SOURCE_NAMES
    from ops.retirement.operator_scope import Scope

    scope = Scope(args.qa_run)
    if scope.qa_run is None:
        raise RuntimeError("operator_stage_explicit_QA_scope_required")
    scope.validate()
    cached = checked_archive(full_source(ROOT), args.source_sha256)
    pin = stage(ROOT, scope.parent / "stage", SOURCE_NAMES, cached=cached)
    print(
        json.dumps(
            {
                "status": "public_stage_created",
                "code_manifest_sha256": pin,
                "private_reads": 0,
                "Docker_actions": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
