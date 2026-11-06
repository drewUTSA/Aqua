"""Fixed Mac/SSH endpoints and metadata-only release attestation checks."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any

from backup_stream import bounded_metadata, private_file, require

PROJECT = Path("/Users/bspear2004/Documents/Aqua")
HOME = Path.home()
AGE_KEYGEN = HOME / ".local/share/aqua-toolchain/age/1.3.2/bin/age-keygen"
AGE_KEYGEN_SHA256 = "c16e229245123d0ad27442317461d63915416cad0294395cd19ca93feb3211ea"
SSH_IDENTITY = HOME / ".ssh/aqua_codex_mac_ed25519"
SSH_HOSTS = HOME / ".ssh/aqua_codex_known_hosts"
HOST_FINGERPRINT = "SHA256:v+WP4CGClEGX9cg2x9Gh+Lvcc17A0mV/+XgTBxlGqb0"
FIELDS = {
    "server_utc",
    "run",
    "guard",
    "nonce",
    "writers_stopped_utc",
    "backend_id",
    "frontend_id",
    "schema_version",
    "commit",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def private_directory(path: Path | str) -> tuple[str, str]:
    """Reject inherited ACLs and symlinks instead of weakening an existing path."""
    path = Path(path)
    require(
        path.is_absolute() and path.resolve() == path, "backup_directory_not_canonical"
    )
    require(
        PROJECT not in path.parents and path != PROJECT,
        "backup_must_be_outside_checkout",
    )
    info = path.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o700,
        "backup_directory_permissions_invalid",
    )
    acl = subprocess.run(
        ["/bin/ls", "-lde", str(path)], capture_output=True, timeout=5, check=True
    ).stdout
    require(
        len(acl) < 8192 and not re.search(rb"(?m)^\s*[0-9]+:", acl),
        "backup_directory_acl_requires_review",
    )
    identity = {
        "path": str(path),
        "device": info.st_dev,
        "inode": info.st_ino,
        "owner": info.st_uid,
        "mode": 0o700,
    }
    acl_record = {"owner": info.st_uid, "mode": 0o700, "extra_acl_entries": []}
    return (
        hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
        hashlib.sha256(json.dumps(acl_record, sort_keys=True).encode()).hexdigest(),
    )


def cipher_hash(path: Path | str) -> str:
    private_file(path)
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        while data := stream.read(65536):
            digest.update(data)
    return digest.hexdigest()


def backup_recipient(identity: Path | str) -> str:
    private_file(identity, maximum=65536)
    info = AGE_KEYGEN.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and not info.st_mode & 0o022
        and hashlib.sha256(AGE_KEYGEN.read_bytes()).hexdigest() == AGE_KEYGEN_SHA256,
        "age_keygen_integrity_failed",
    )
    result = subprocess.run(
        [str(AGE_KEYGEN), "-y", str(identity)],
        capture_output=True,
        timeout=10,
        check=False,
    )
    recipient = result.stdout.decode().strip()
    require(
        result.returncode == 0
        and re.fullmatch(r"age1[0-9a-z]{55,90}", recipient) is not None,
        "dedicated_backup_identity_required",
    )
    return recipient


def ssh_command(arguments: list[str]) -> list[str]:
    """Use the verified host/key directly; no ambient agent/proxy/config hooks."""
    private_file(SSH_IDENTITY, maximum=65536)
    private_file(SSH_HOSTS, maximum=65536)
    import base64

    line = SSH_HOSTS.read_text().strip().split()
    require(
        len(line) == 3 and line[:2] == ["192.168.1.200", "ssh-ed25519"],
        "ssh_host_file_changed",
    )
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(base64.b64decode(line[2], validate=True)).digest()
    ).decode().rstrip("=")
    require(fingerprint == HOST_FINGERPRINT, "ssh_host_fingerprint_changed")
    return [
        "/usr/bin/ssh",
        "-F",
        "/dev/null",
        "-T",
        "-i",
        str(SSH_IDENTITY),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UserKnownHostsFile=" + str(SSH_HOSTS),
        "-o",
        "ForwardAgent=no",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "PermitLocalCommand=no",
        "-o",
        "ConnectTimeout=10",
        "ben2004@192.168.1.200",
        *arguments,
    ]


def stage_arguments(stage: Path | str, action: str) -> list[str]:
    require(
        re.fullmatch(
            r"/srv/bank-ai/\.check-results/p11a-release-[0-9A-Za-z_-]{8,90}", str(stage)
        )
        is not None,
        "release_stage_invalid",
    )
    require(
        action in {"show", "receive-backup", "receive-retention"},
        "attestation_action_invalid",
    )
    return [
        "/usr/bin/python3",
        "-E",
        "-s",
        "-B",
        str(stage) + "/attest.py",
        action,
        "--root",
        str(stage),
    ]


def remote_metadata(
    stage: Path | str, action: str, data: bytes | None = None
) -> dict[str, Any]:
    raw = bounded_metadata(ssh_command(stage_arguments(stage, action)), data)
    value = json.loads(raw)
    if action == "show":
        require(
            set(value) == FIELDS and value.get("schema_version") == 7,
            "stopped_writer_attestation_invalid",
        )
    else:
        require(
            value.get("status") == "accepted"
            and value.get("accepted_action") == action,
            "server_attestation_not_accepted",
        )
    return value


def stable_attestation(
    before: dict[str, Any], after: dict[str, Any], commit: str
) -> None:
    require(re.fullmatch(r"[a-f0-9]{40}", commit) is not None, "release_commit_invalid")
    require(before["commit"] == after["commit"] == commit, "release_commit_changed")
    require(
        {k: before[k] for k in FIELDS - {"server_utc"}}
        == {k: after[k] for k in FIELDS - {"server_utc"}},
        "stopped_writer_authority_changed",
    )
    for value in (before, after):
        server_time = datetime.fromisoformat(value["server_utc"])
        stopped = datetime.fromisoformat(value["writers_stopped_utc"])
        require(
            server_time.tzinfo is not None
            and stopped.tzinfo is not None
            and stopped <= server_time
            and abs((utcnow() - server_time).total_seconds()) <= 30,
            "server_attestation_time_invalid",
        )
