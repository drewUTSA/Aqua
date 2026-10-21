"""Offline high-confidence secret checks over tracked/staged source, never .git.

This is a guardrail, not proof that arbitrary secrets cannot exist. Findings
contain only a relative path, line and rule; never print the matched value.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess

RULES = {
    "private-key": re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    ),
    "google-api-key": re.compile(rb"AIza[0-9A-Za-z_-]{35}"),
    "github-token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{36,255}"),
    "resend-token": re.compile(rb"\bre_[A-Za-z0-9]{32,100}\b"),
}


def scan(path: str, content: bytes) -> list[dict]:
    """Return metadata only so a failed check cannot disclose its finding."""
    return [
        {"path": path, "line": content.count(b"\n", 0, match.start()) + 1, "rule": rule}
        for rule, pattern in RULES.items()
        for match in pattern.finditer(content)
    ]


def check(root: Path, names: list[str]) -> list[dict]:
    """Reject tracked runtime files and scan text files without following links."""
    findings = []
    for name in names:
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("manifest entries must stay within the source root")
        path = root / name
        if path.is_symlink():
            findings.append({"path": name, "rule": "symlink-requires-review"})
            continue
        if not path.is_file():
            continue  # deleted tracked file
        if path.name.startswith(".env") and path.name != ".env.example":
            findings.append({"path": name, "rule": "runtime-environment-file"})
            continue
        content = path.read_bytes()
        if b"\0" not in content:
            findings.extend(scan(name, content))
    return findings


def self_test() -> None:
    """Red canaries prove detection and that reports omit the sensitive bytes."""
    canary = b"gh" + b"p_" + b"x" * 36
    findings = scan("fixture.txt", b"line one\n" + canary)
    assert findings == [{"path": "fixture.txt", "line": 2, "rule": "github-token"}]
    assert canary.decode() not in json.dumps(findings)
    assert (
        scan("public.txt", b"GOOGLE_CLIENT_ID=example.apps.googleusercontent.com") == []
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument(
        "--manifest", type=Path, help="JSON list of reviewable relative paths"
    )
    args = parser.parse_args()
    self_test()
    if args.manifest:
        names = json.loads(args.manifest.read_text(encoding="utf-8"))
    else:
        names = (
            subprocess.check_output(
                ["git", "ls-files", "-z", "--cached"], cwd=args.root
            )
            .decode()
            .split("\0")
        )
    findings = check(args.root, [name for name in names if name])
    print(
        json.dumps({"status": "failed" if findings else "passed", "findings": findings})
    )
    raise SystemExit(bool(findings))
