"""Verify the extracted bank MCP demo and install its locked wheels into a dedicated local environment."""

from contextlib import contextmanager
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".aqua-demo-venv"
LOCK = ".aqua-demo-setup.lock"
RECEIPT = ".aqua-demo-install.json"
FRESH = "The existing installation could not be verified. Use a fresh extraction."


def verify():
    manifest = json.loads((ROOT / "MANIFEST.json").read_bytes())
    expected_names = set(manifest["members"]) | {"MANIFEST.json"}
    present = set()
    for directory, directories, filenames in os.walk(ROOT, followlinks=False):
        parent = Path(directory)
        if parent == ROOT and ENV.name in directories:
            directories.remove(ENV.name)
        if any((parent / d).resolve() != parent / d for d in directories):
            raise ValueError(
                "Extract the demo into a fresh folder without linked directories"
            )
        for name in filenames:
            target = parent / name
            if target.resolve() != target or not target.is_file():
                raise ValueError("Unexpected linked demo file")
            relative = target.relative_to(ROOT).as_posix()
            if relative not in {LOCK, RECEIPT}:
                present.add(relative)
    if present != expected_names:
        raise ValueError("Extract the complete demo into a dedicated folder")
    for name, expected in manifest["members"].items():
        if sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"File verification failed for {name}")
    return manifest


@contextmanager
def install_lock():
    path = ROOT / LOCK
    if path.resolve() != path or (path.exists() and not path.is_file()):
        raise ValueError("Unexpected installation lock location")
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def installation_receipt(manifest):
    """Use the parent interpreter to hash the complete venv, including bytecode."""

    def fail(error):
        raise error

    digest = sha256()
    for directory, directories, filenames in os.walk(
        ENV, followlinks=False, onerror=fail
    ):
        directories.sort()
        for name in sorted([*directories, *filenames]):
            entry = Path(directory) / name
            info = entry.lstat()
            field = [entry.relative_to(ENV).as_posix(), stat.S_IMODE(info.st_mode)]
            if stat.S_ISLNK(info.st_mode):
                # Linux venv can create lib64 -> lib. Executables are copied.
                if not entry.resolve(strict=True).is_relative_to(ENV):
                    raise ValueError(FRESH)
                field.extend(["link", os.readlink(entry)])
                if name in directories:
                    directories.remove(name)
            elif (
                getattr(info, "st_file_attributes", 0)
                & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise ValueError(FRESH)
            elif stat.S_ISDIR(info.st_mode):
                field.append("directory")
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                with entry.open("rb") as stream:
                    field.extend(
                        [
                            "file",
                            info.st_size,
                            file_digest(stream, "sha256").hexdigest(),
                        ]
                    )
            else:
                raise ValueError(FRESH)
            digest.update(json.dumps(field, ensure_ascii=True).encode("ascii") + b"\n")
    value = {
        "format": 1,
        "environment": str(ENV),
        "source": manifest["source"],
        "manifest_sha256": sha256((ROOT / "MANIFEST.json").read_bytes()).hexdigest(),
        "environment_sha256": digest.hexdigest(),
    }
    return (json.dumps(value, indent=2) + "\n").encode()


def install_wheels(interpreter):
    subprocess.run(
        [sys.executable, "-I", "-m", "venv", "--copies", str(ENV)], check=True
    )
    environment = {
        **os.environ,
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    }
    for lock in ("requirements-bootstrap.txt", "requirements-lock.txt"):
        subprocess.run(
            [
                interpreter,
                "-I",
                "-m",
                "pip",
                "--isolated",
                "--disable-pip-version-check",
                "install",
                "--no-index",
                "--no-cache-dir",
                "--only-binary=:all:",
                "--require-hashes",
                "--find-links",
                str(ROOT / "wheels"),
                "-r",
                str(ROOT / "tools/bank_demo" / lock),
            ],
            cwd=ROOT,
            env=environment,
            check=True,
        )
    subprocess.run(
        [interpreter, "-I", "-m", "pip", "--isolated", "check"],
        cwd=ROOT,
        env=environment,
        check=True,
    )


def install():
    if (
        sys.version_info[:2] != (3, 12)
        or platform.machine().lower() not in {"amd64", "x86_64"}
        or sys.maxsize <= 2**32
    ):
        raise RuntimeError("Use 64-bit CPython 3.12 for Windows x64 or Linux x86_64")
    if platform.python_implementation() != "CPython" or sys.platform not in {
        "win32",
        "linux",
    }:
        raise RuntimeError("Use CPython on Windows or glibc Linux")
    if Path(sys.prefix).resolve() == ENV:
        raise RuntimeError("Run setup with your system Python 3.12 interpreter.")
    interpreter = ENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    with install_lock():
        manifest = verify()
        marker = ENV / "aqua-demo-source"
        receipt = ROOT / RECEIPT
        if ENV.resolve() != ENV or ENV.is_junction():
            raise ValueError(FRESH)
        if ENV.exists() or receipt.exists():
            if (
                not ENV.is_dir()
                or not receipt.is_file()
                or not marker.is_file()
                or marker.is_symlink()
            ):
                raise ValueError(FRESH)
            if marker.read_bytes() != manifest["source"].encode(
                "ascii"
            ) or receipt.read_bytes() != installation_receipt(manifest):
                raise ValueError(FRESH)
        else:
            ENV.mkdir()
            marker.write_text(manifest["source"], encoding="ascii")
            install_wheels(interpreter)
            # An interrupted first installation has no complete receipt and cannot be run on retry.
            payload = installation_receipt(manifest)
            with receipt.open("xb") as stream:
                stream.write(payload)
        print("MCP host entry for this extraction")
        print(
            json.dumps(
                {
                    "mcpServers": {
                        "aqua-fictional-bank": {
                            "command": str(interpreter),
                            "args": [
                                "-B",
                                "-I",
                                str(ROOT / "serve_demo.py"),
                                "--persona",
                                "analyst",
                            ],
                        }
                    }
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    install()
