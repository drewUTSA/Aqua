"""Public authority pins, fixed SSH command and stopped-writer metadata."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import re
import shlex

from authority_support import HEX, HOLDERS, decode, host, require, stream


@dataclass(frozen=True)
class Expected:
    """Public pins supplied separately by the reviewed install/capture ceremony."""

    installation_id: str
    identity_key_id: str
    key_commitment: str
    public_key: str
    runtime_image: str
    source_sha256: str
    profile_sha256: str
    exporter_sha256: str
    restore_verifier_sha256: str
    maintenance_nonce: str
    maintenance_receipt_sha256: str
    protected_chain_sha256: str
    head_hex: str
    verification_chain: bytes = field(default=b"", repr=False, compare=False)

    def checked(self):
        for name in (
            "key_commitment",
            "public_key",
            "source_sha256",
            "profile_sha256",
            "exporter_sha256",
            "restore_verifier_sha256",
            "maintenance_receipt_sha256",
            "protected_chain_sha256",
        ):
            require(
                type(getattr(self, name)) is str and HEX.fullmatch(getattr(self, name)),
                "authority_public_pin_invalid",
            )
        require(
            re.fullmatch(r"sha256:[a-f0-9]{64}", self.runtime_image)
            and re.fullmatch(r"[a-f0-9]{32}", self.maintenance_nonce),
            "authority_scope_invalid",
        )
        require(
            type(self.head_hex) is str
            and re.fullmatch(r"[a-f0-9]{416}", self.head_hex),
            "independent_signed_head_required",
        )
        head = decode(
            bytes.fromhex(self.head_hex),
            bytes.fromhex(self.public_key),
            installation=self.installation_id,
            key_id=self.identity_key_id,
            commitment=bytes.fromhex(self.key_commitment),
        )
        return head


def remote_command(stage, action, expected):
    """Build only a fixed stage helper; SSH preserves its existing verified pins."""
    expected.checked()
    require(
        re.fullmatch(
            r"/srv/bank-ai/\.check-results/p11bc-release-[0-9]{17}-[a-f0-9]{8}",
            str(stage),
        ),
        "authority_stage_invalid",
    )
    require(action in {"head", "export"}, "authority_action_invalid")
    path = str(stage) + "/ops/retirement/export.py"
    program = """import hashlib,os,pathlib,stat,sys
p=pathlib.Path(sys.argv[1]);fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
with os.fdopen(fd,'rb') as f:
 s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode) and s.st_uid==1000 and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==0o600 and 0<s.st_size<=131072
 raw=f.read(131073);assert len(raw)==s.st_size and p.resolve()==p and hashlib.sha256(raw).hexdigest()==sys.argv[2]
sys.argv=[str(p),'--action',sys.argv[3],'--profile-sha256',sys.argv[4]]
exec(compile(raw,str(p),'exec'),{'__name__':'__main__','__file__':str(p)})
"""
    return host.ssh_command(
        [
            shlex.join(
                [
                    "/usr/bin/python3",
                    "-E",
                    "-s",
                    "-B",
                    "-c",
                    program,
                    path,
                    expected.exporter_sha256,
                    action,
                    expected.profile_sha256,
                ]
            )
        ]
    )


def metadata(value, expected, now=None):
    """Authenticated helper evidence is capture-point authority, not global RPO0."""
    head = expected.checked()
    stable = {
        name: getattr(expected, name)
        for name in (
            "installation_id",
            "identity_key_id",
            "key_commitment",
            "public_key",
            "runtime_image",
            "source_sha256",
            "profile_sha256",
            "maintenance_nonce",
            "maintenance_receipt_sha256",
            "protected_chain_sha256",
            "head_hex",
        )
    }
    require(
        type(value) is dict and all(value.get(k) == v for k, v in stable.items()),
        "authority_head_or_profile_changed",
    )
    require(
        value.get("schemaVersion") == 1
        and type(value.get("schemaVersion")) is int
        and value.get("mode") == "retained_authority_stopped_writers"
        and value.get("total_host_restore_supported") is False,
        "authority_mode_invalid",
    )
    require(
        type(value.get("sequence")) is int
        and value["sequence"] == head.sequence
        and value.get("event_digest") == head.event_digest.hex(),
        "authority_signed_sequence_mismatch",
    )
    require(
        value.get("holders_stopped") == {name: "absence_confirmed" for name in HOLDERS},
        "authority_holders_not_absent",
    )
    try:
        checked = datetime.fromisoformat(value["checked_utc"])
        expires = datetime.fromisoformat(value["maintenance_expires_utc"])
        now = now or datetime.now(timezone.utc)
        require(
            checked.tzinfo is not None
            and expires.tzinfo is not None
            and abs((now - checked).total_seconds()) <= 30
            and now < expires <= now + timedelta(seconds=300),
            "authority_maintenance_expired",
        )
    except (KeyError, ValueError, TypeError):
        raise stream.BackupError("authority_maintenance_invalid") from None
    return {
        **stable,
        "maintenance_expires_utc": value["maintenance_expires_utc"],
        "sequence": head.sequence,
        "event_digest": head.event_digest.hex(),
    }
