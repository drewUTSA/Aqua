"""Offline app-only repair against retained live authority; total-host closed.

Explicit execution proves old writers absent, reapplies the exact reviewed
restore-session fence, and transfers only the physical purge lock to its owned
cap-zero child. It never restores the independent database or starts writers.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import signal

if __package__:
    from . import maintenance
    from .operator_scope import PRODUCTION, Scope
    from .export_resources import Owned
    from .install import sql, sources
    from .operator_files import PRIVATE, parse, read, pinned
else:
    import maintenance
    from operator_scope import PRODUCTION, Scope
    from export_resources import Owned
    from install import sql, sources
    from operator_files import PRIVATE, parse, read, pinned

STAGE = Path(__file__).resolve().parent

PEER = """
import json,os,pathlib,re
from contextlib import nullcontext
import psycopg
from retirement.checkpoint import ProtectedFile
from retirement.mail_physical import gate,validate
from retirement.settings import private_bytes
from storage.config import StorageSettings,validate_dsn
from storage.pool import Storage
root=pathlib.Path('/run/aqua-retirement')
if any(name.startswith('PG') for name in os.environ) or not os.statvfs(root).f_flag & os.ST_RDONLY:raise RuntimeError('recovery_context')
value=json.loads(private_bytes(root/'verification.json',4096))
if value!=expected:raise RuntimeError('recovery_profile_changed')
app=private_bytes(root/'app.dsn',512).decode()
if validate_dsn(app,'aqua_app_runtime').get('host')!='/run/aqua-app-db':raise RuntimeError('recovery_app_socket')
recovery=private_bytes(root/'recovery.dsn',512).decode()
if not re.fullmatch(r'postgresql://aqua_retirement_recovery:[A-Za-z0-9_-]{43}@/aqua_retirement\\?host=/run/aqua-app-db&port=5432&sslmode=disable',recovery):raise RuntimeError('recovery_role')
protected=ProtectedFile(root/'checkpoints.bin',owner_uid=1000,public_key=bytes.fromhex(value['public_key']),installation=value['installation_id'],key_id=value['identity_key_id'],commitment=bytes.fromhex(value['key_commitment']))
validate()
storage=Storage(StorageSettings(True,app,4,8,2))
storage.open()
try:
 with psycopg.connect(recovery,autocommit=True,connect_timeout=2) as conn:
  row=conn.execute("SELECT current_database(),current_user,session_user,rolsuper,rolinherit,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolconnlimit FROM pg_roles WHERE rolname=current_user").fetchone()
  if row!=('aqua_retirement','aqua_retirement_recovery','aqua_retirement_recovery',False,False,False,False,False,False,1):raise RuntimeError('recovery_exact_role')
  for name in ('fsync','full_page_writes','synchronous_commit','default_transaction_read_only'):
   if conn.execute('SHOW '+name).fetchone()!=('on',):raise RuntimeError('recovery_durability')
  outcome=sys.modules['ops.retirement.recovery_driver'].app_only(storage,conn,protected,expected_protected_sha256=protected_sha,purge_guard=lambda closed:gate() if closed else nullcontext(True),batch_limit=128)
 print(json.dumps(outcome,sort_keys=True))
finally:
 storage.close()
"""


def program(cache: dict, public: dict, protected: str) -> str:
    raw = "import sys,types\n"
    for name in ("ops", "ops.retirement"):
        raw += f"module=types.ModuleType({name!r});module.__path__=[];sys.modules[{name!r}]=module\n"
    for name in ("operator_deadline.py", "recovery_driver.py"):
        module = "ops.retirement." + name[:-3]
        raw += f'module=types.ModuleType({module!r});module.__file__={name!r};module.__package__="ops.retirement";sys.modules[{module!r}]=module\nexec(compile({cache[name]!r},{name!r},"exec"),module.__dict__)\n'
    return (
        raw
        + "expected="
        + repr(public)
        + "\nprotected_sha="
        + repr(protected)
        + "\n"
        + PEER
    )


class Recovery(Owned):
    roles = frozenset({"recovery"})
    purpose = "retirement-offline-recovery"

    def __init__(self, value, code, scope=PRODUCTION):
        super().__init__(value, scope=scope)
        self.name = self.name.replace("archive", "recovery")
        self.code = code

    def create(self, role="recovery", action=""):
        if role != "recovery" or self.attempted:
            raise RuntimeError("recovery_role_reused")
        self.attempted.append(role)
        self.uncertain.add(role)
        args = [
            "container",
            "create",
            "--pull=never",
            "--name=" + self.name + "-" + role,
            "--label=io.aqua.run=" + self.name,
            "--label=io.aqua.purpose=" + self.purpose,
            *(
                ["--label=io.aqua.qa-run=" + self.scope.qa_run]
                if self.scope.qa_run is not None
                else []
            ),
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--user=1000:1000",
            "--memory=1g",
            "--memory-swap=1g",
            "--cpus=1",
            "--pids-limit=64",
            "--restart=no",
            "--log-driver=none",
            "--no-healthcheck",
            "--stop-timeout=1",
            "--workdir=/app",
            "--mount=type=bind,src="
            + str(self.private / "operator/recovery")
            + ",dst=/run/aqua-retirement,readonly",
            "--mount=type=bind,src="
            + str(self.private / "authority/checkpoints.bin")
            + ",dst=/run/aqua-retirement/checkpoints.bin,readonly",
            "--mount=type=bind,src="
            + str(
                (
                    PRIVATE.parent / "mail"
                    if self.scope is PRODUCTION
                    else self.scope.mail
                )
                / "physical.lock"
            )
            + ",dst=/run/aqua-retirement/mail-worker.lock,readonly",
            "--mount=type=volume,src=" + self.socket + ",dst=/run/aqua-app-db,readonly",
            "--entrypoint=python",
            self.profile["runtime_image"],
            "-E",
            "-s",
            "-B",
            "-c",
            self.code,
        ]
        identifier = self.remember(role, self.command(*args).decode().strip())
        if identifier != self.inspect(role):
            raise RuntimeError("recovery_create_identity")
        self.uncertain.discard(role)
        return identifier


def execute(expected: str, protected: str, scope=PRODUCTION) -> dict:
    scope.validate()
    root = PRIVATE if scope is PRODUCTION else scope.private
    if not re.fullmatch(r"[a-f0-9]{64}", expected) or not re.fullmatch(
        r"[a-f0-9]{64}", protected
    ):
        raise RuntimeError("recovery_explicit_profile_and_retained_chain_required")
    value = pinned(root / "operator/recovery.json", expected)
    fields = {
        "schemaVersion",
        "runtime_image",
        "source_sha256",
        "plan_sha256",
        "code_manifest_sha256",
        "verification_sha256",
        "fence_sha256",
    }
    if (
        set(value) != fields
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
    ):
        raise RuntimeError("recovery_profile_invalid")
    for name in fields - {"schemaVersion"}:
        pattern = r"sha256:[a-f0-9]{64}" if name == "runtime_image" else r"[a-f0-9]{64}"
        if type(value[name]) is not str or not re.fullmatch(pattern, value[name]):
            raise RuntimeError("recovery_profile_invalid")
    cache = sources(value["code_manifest_sha256"])
    if (
        hashlib.sha256(cache["restore_session_fence.sql"]).hexdigest()
        != value["fence_sha256"]
    ):
        raise RuntimeError("recovery_source_bytes_changed")
    verification = read(root / "operator/recovery/verification.json", 4096)
    if hashlib.sha256(verification).hexdigest() != value["verification_sha256"]:
        raise RuntimeError("recovery_verification_profile_changed")
    public = parse(verification)
    if (public.get("runtime_image"), public.get("source_sha256")) != (
        value["runtime_image"],
        value["source_sha256"],
    ):
        raise RuntimeError("recovery_runtime_source_changed")
    previous = {}
    cleaning = False

    def cancel(number, frame):
        if not cleaning:
            raise RuntimeError("recovery_cancelled")

    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGALRM):
        previous[number] = signal.getsignal(number)
        signal.signal(number, cancel)
    signal.alarm(120)
    try:
        with maintenance.Hold(value["plan_sha256"], scope=scope) as held:
            if (held.value["runtime_image"], held.value["source_sha256"]) != (
                value["runtime_image"],
                value["source_sha256"],
            ):
                raise RuntimeError("recovery_plan_changed")
            held.require(9)
            owner = Recovery(value, program(cache, public, protected), scope=scope)
            try:
                if (
                    owner.command(
                        "image", "inspect", value["runtime_image"], "--format={{.Id}}"
                    ).strip()
                    != value["runtime_image"].encode()
                ):
                    raise RuntimeError("recovery_image_changed")
                sql(
                    held.value["database_id"],
                    b"\\connect aqua_app\n" + cache["restore_session_fence.sql"],
                )
                identifier = owner.create()
                held.recovery_handoff()
                output = owner.command(
                    "start", "--attach", identifier, maximum_seconds=90
                )
                state = owner.command(
                    "inspect",
                    identifier,
                    "--format={{json .State.Running}}\n{{json .State.ExitCode}}",
                )
                result = json.loads(output)
                if (
                    state.splitlines() != [b"false", b"0"]
                    or result.get("mode") != "retained_authority_app_only"
                    or result.get("protected_sha256") != protected
                    or result.get("ready") is not True
                    or result.get("pending_manifest") is not False
                ):
                    raise RuntimeError("recovery_not_ready_stay_maintenance")
            finally:
                cleaning = True
                signal.alarm(0)
                owner.close()
            held.require(9)
            return {
                **result,
                "writers_resumed": False,
                "cron_resumed": False,
                "physical_mail_validation": "child_owner_mode_readonly_named_inode",
                "total_host_restore_supported": False,
            }
    finally:
        cleaning = True
        signal.alarm(0)
        for number, handler in previous.items():
            signal.signal(number, handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--profile-sha256", default="")
    parser.add_argument("--protected-sha256", default="")
    parser.add_argument("--qa-run")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "private_reads": 0,
                    "writes": 0,
                    "Docker_actions": 0,
                    "total_host_restore_supported": False,
                }
            )
        )
        return
    print(
        json.dumps(
            execute(
                args.profile_sha256,
                args.protected_sha256,
                scope=Scope(args.qa_run) if args.qa_run is not None else PRODUCTION,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
