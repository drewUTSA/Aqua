"""Build a reproducible, fictional bank MCP archive from this Git checkout's HEAD."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener
from zipfile import ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[2]
BANK = "tools/bank_demo"
LOCKS = (f"{BANK}/requirements-bootstrap.txt", f"{BANK}/requirements-lock.txt")
SOURCES = (
    "eval/__init__.py",
    *(
        f"eval/banking/{name}.py"
        for name in (
            "__init__",
            "catalog",
            "data",
            "knowledge",
            "proposals",
            "reports",
            "scope",
        )
    ),
    *(
        f"eval/{name}.py"
        for name in (
            "monthly_trend",
            "monthly_trend_contract",
            "monthly_trend_evaluation",
        )
    ),
    *(
        f"mcp_demo/{name}.py"
        for name in (
            "__init__",
            "__main__",
            "data",
            "finance",
            "finance_schema",
            "guidance",
            "protocol",
            "reports",
            "server",
            "trends",
            "web",
        )
    ),
    "mcp_demo/fixtures/bank.json",
    *LOCKS,
)
LAUNCH_FILES = ("README.md", "setup_demo.py", "serve_demo.py", "walkthrough.py")


class DirectDownload(HTTPRedirectHandler):
    """Package metadata and immutable wheel URLs must be served by the named host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], timeout=30)


def requirements(raw):
    """Reject any lock syntax except pinned projects and explicit SHA-256 wheel hashes."""
    result = []
    for text in (
        raw.decode("utf8").replace("\\\r\n", " ").replace("\\\n", " ").splitlines()
    ):
        line = text.strip()
        if not line or line.startswith("#") or line == "--only-binary=:all:":
            continue
        match = re.fullmatch(
            r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)(?:;\s*sys_platform\s*==\s*"(?:win32|linux)")?'
            r"((?:\s+--hash=sha256:[0-9a-f]{64})+)",
            line,
        )
        if not match:
            raise ValueError("Unsupported entry in the bank demo wheel lock")
        name, version, pins = match.groups()
        result.append(
            (name, version, frozenset(re.findall(r"sha256:([a-f0-9]{64})", pins)))
        )
    if not result:
        raise ValueError("Empty bank demo wheel lock")
    return result


def download(url, host, maximum):
    def expected(location):
        parts = urlsplit(location)
        return parts.scheme == "https" and parts.netloc == host

    if not expected(url):
        raise ValueError("Unexpected wheel or metadata URL")
    with build_opener(DirectDownload).open(url, timeout=30) as response:
        if not expected(response.geturl()):
            raise ValueError("Unexpected wheel or metadata redirect")
        content = response.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("Wheel or metadata exceeded the download bound")
    return content


def wheels(requirement):
    name, version, pins = requirement
    listing = json.loads(
        download(f"https://pypi.org/pypi/{name}/{version}/json", "pypi.org", 3_000_000)
    )
    result = {}
    found = set()
    for info in listing["urls"]:
        digest = info["digests"]["sha256"]
        if digest not in pins:
            continue
        filename = info["filename"]
        if (
            not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", filename)
            or info["packagetype"] != "bdist_wheel"
            or info["yanked"]
            or not 0 < info["size"] <= 32_000_000
        ):
            raise ValueError(f"Unexpected metadata for a locked wheel of {name}")
        data = download(info["url"], "files.pythonhosted.org", info["size"])
        if len(data) != info["size"] or sha256(data).hexdigest() != digest:
            raise ValueError(f"Wheel bytes did not match the lock for {filename}")
        if digest in found or filename in result:
            raise ValueError(f"Repeated wheel for {name}")
        found.add(digest)
        result[filename] = data
    if found != pins:
        raise ValueError(f"Missing locked wheel for {name} {version}")
    return result


def build(destination):
    destination = destination.absolute()
    if destination.exists():
        raise FileExistsError("Choose a new output directory")
    commit = git("rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip()
    files = {name: git("show", f"{commit}:{name}") for name in SOURCES}
    for name in LAUNCH_FILES:
        files[name] = git("show", f"{commit}:{BANK}/offline/{name}")
    locked = [item for path in LOCKS for item in requirements(files[path])]
    names = [re.sub(r"[-_.]+", "-", name).lower() for name, _, _ in locked]
    if len(set(names)) != len(names):
        raise ValueError("A distribution appears twice in the wheel locks")
    with ThreadPoolExecutor(max_workers=3) as pool:
        for group in pool.map(wheels, locked):
            for name, data in group.items():
                path = f"wheels/{name}"
                if path in files:
                    raise ValueError(f"Repeated archive member {path}")
                files[path] = data
    manifest = {
        "source": commit,
        "members": {
            name: sha256(data).hexdigest() for name, data in sorted(files.items())
        },
    }
    files["MANIFEST.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=destination.parent, prefix="aqua-mcp-build-"
    ) as temporary:
        output = Path(temporary) / "complete"
        output.mkdir()
        path = output / "Aqua-fictional-bank-MCP-offline.zip"
        with ZipFile(path, "x") as archive:
            for name, data in sorted(files.items()):
                info = ZipInfo(name, (2026, 11, 20, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        report = {
            "file": path.name,
            "source": commit,
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
            "sourceFiles": len(SOURCES),
            "wheels": sum(p.startswith("wheels/") for p in files),
            "lockedDistributions": len(locked),
            "members": len(files),
        }
        (output / "PACKAGE.json").write_bytes(
            (json.dumps(report, indent=2) + "\n").encode()
        )
        output.rename(destination)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "destination",
        type=Path,
        help="A new directory for the ZIP and its SHA-256 receipt",
    )
    print(json.dumps(build(parser.parse_args().destination), indent=2))
