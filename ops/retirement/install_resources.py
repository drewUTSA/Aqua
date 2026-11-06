"""Exact-owned create-only installer processes; no flag-clear/rollback operation."""

import json
import hashlib

if __package__:
    from .export_resources import Owned
    from .operator_files import PRIVATE
    from .operator_scope import PRODUCTION
else:
    from export_resources import Owned
    from operator_files import PRIVATE
    from operator_scope import PRODUCTION


class Installer(Owned):
    roles = frozenset({"materialize", "initializer", "setter", "genesis_ack"})
    purpose = "retirement-install-operator"

    @property
    def private(self):
        return PRIVATE if self.scope is PRODUCTION else self.scope.private

    def __init__(self, profile: dict, programs: dict[str, bytes], scope=PRODUCTION):
        super().__init__(profile, scope)
        self.name = self.name.replace("archive", "install")
        self.programs = programs
        self.genesis = None
        self.initializer_absent = False
        self.setter_absent = False

    def create(self, role: str, action: str = "") -> str:
        if role not in self.roles or role in self.attempted:
            raise RuntimeError("retirement_install_role_reused_or_invalid")
        if role == "setter" and not self.initializer_absent:
            raise RuntimeError("retirement_install_initializer_exit_required")
        if role == "genesis_ack" and not self.setter_absent:
            raise RuntimeError("retirement_install_setter_exit_required")
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
            "--memory=128m",
            "--memory-swap=128m",
            "--cpus=1",
            "--pids-limit=32",
            "--restart=no",
            "--log-driver=none",
            "--no-healthcheck",
            "--stop-timeout=1",
            "--workdir=/app",
        ]
        argv = ["--execute"]
        if role == "materialize":
            args += [
                "--user=1000:1000",
                "--mount=type=bind,src="
                + str(self.private)
                + ",dst="
                + str(PRODUCTION.private),
            ]
            argv += [
                "--runtime-image",
                self.profile["runtime_image"],
                "--source-sha256",
                self.profile["source_sha256"],
            ]
        elif role == "initializer":
            args += [
                "--user=1000:1000",
                "--mount=type=bind,src="
                + str(self.private / "initializer")
                + ",dst=/run/aqua-retirement-initializer,readonly",
                "--mount=type=bind,src="
                + str(self.private / "authority")
                + ",dst=/run/aqua-retirement-authority",
            ]
        elif role == "setter":
            args += [
                "--user=0:0",
                "--cap-add=DAC_OVERRIDE",
                "--cap-add=FOWNER",
                "--cap-add=LINUX_IMMUTABLE",
                "--mount=type=bind,src="
                + str(self.private / "authority")
                + ",dst=/run/aqua-retirement-provisioning",
            ]
            argv += [
                "--device",
                str(self.genesis["device"]),
                "--inode",
                str(self.genesis["inode"]),
                "--genesis-sha256",
                self.genesis["genesis_sha256"],
            ]
        else:
            args += [
                "--user=1000:1000",
                "--mount=type=bind,src="
                + str(self.private / "authority")
                + ",dst=/run/aqua-retirement",
                "--mount=type=bind,src="
                + str(self.private / "host")
                + ",dst=/run/aqua-retirement-host,readonly",
                "--mount=type=volume,src="
                + self.socket
                + ",dst=/run/aqua-app-db,readonly",
            ]
            argv = []
        source = self.programs[role]
        # Public program bytes were manifest-checked and cached before keys exist.
        # No source path is imported after that check. close_fds/no pass_fds is
        # inherited from Owned.command, and the initializer is actually removed.
        bootstrap = (
            "import sys;sys.argv="
            + repr([role, *argv])
            + ";exec(compile("
            + repr(source)
            + ","
            + repr(role)
            + ',"exec"),{"__name__":"__main__","__file__":"/operator/'
            + role
            + '.py"})'
        )
        args += [
            "--entrypoint=python",
            self.profile["runtime_image"],
            "-E",
            "-s",
            "-B",
            "-c",
            bootstrap,
        ]
        identifier = self.remember(role, self.command(*args).decode().strip())
        if identifier != self.inspect(role):
            raise RuntimeError("retirement_install_create_identity_mismatch")
        self.uncertain.discard(role)
        return identifier

    def once(self, role: str) -> dict:
        identifier = self.create(role)
        try:
            raw = self.command("container", "start", "--attach", identifier)
            state = self.command(
                "inspect",
                identifier,
                "--format={{json .State.Running}}\n{{json .State.ExitCode}}",
            )
            if state.splitlines() != [b"false", b"0"] or len(raw) > 16384:
                raise RuntimeError("retirement_install_role_exit_unconfirmed")
            value = json.loads(raw)
            if type(value) is not dict:
                raise RuntimeError("retirement_install_role_result_invalid")
        finally:
            if not self.remove(role):
                raise RuntimeError("retirement_install_role_absence_unconfirmed")
        if role == "initializer":
            if (
                set(value)
                != {
                    "device",
                    "inode",
                    "genesis_sha256",
                    "initializer_exit_required_before_flag",
                    "signer_admitted",
                }
                or value["initializer_exit_required_before_flag"] is not True
                or value["signer_admitted"] is not False
                or any(
                    type(value[key]) is not int or value[key] <= 0
                    for key in ("device", "inode")
                )
            ):
                raise RuntimeError("retirement_install_genesis_receipt_invalid")
            path = self.private / "authority/checkpoints.bin"
            meta = path.lstat()
            if (meta.st_dev, meta.st_ino) != (
                value["device"],
                value["inode"],
            ) or hashlib.sha256(path.read_bytes()).hexdigest() != value[
                "genesis_sha256"
            ]:
                raise RuntimeError("retirement_install_genesis_inode_changed")
            self.genesis = value
            self.initializer_absent = True
        elif role == "setter":
            if (
                value.get("status") != "append_provisioned"
                or value.get("signer_admitted") is not False
                or value.get("setter_exit_required_before_signer") is not True
                or any(
                    value.get(key) != self.genesis[key]
                    for key in ("device", "inode", "genesis_sha256")
                )
            ):
                raise RuntimeError("retirement_install_setter_receipt_invalid")
            self.setter_absent = True
        elif role == "genesis_ack" and value != {
            "status": "genesis_acknowledged",
            "sequence": 0,
        }:
            raise RuntimeError("retirement_install_genesis_ACK_invalid")
        return value


def ack_program(host_source: bytes) -> bytes:
    """Use the reviewed strict host parser, cap-one pool and real publisher."""
    prefix = (
        'import types,sys\nmodule=types.ModuleType("_checked_host");module.__file__="/operator/host-sources/retirement_host.py";sys.modules[module.__name__]=module\n'
        + "exec(compile("
        + repr(host_source)
        + ',module.__file__,"exec"),module.__dict__)\n'
    )
    suffix = """
from retirement.checkpoint import ProtectedFile
from retirement.publisher import HostPublisher
settings=module.parse_settings(module.read_private(module.HOST_DIRECTORY/'host.json',4096))
key=module.signing_key(module.HOST_DIRECTORY/'signing.key',settings.public_key)
pool=module.pool_for(settings)
protected=ProtectedFile(module.CHECKPOINT_DIRECTORY/'checkpoints.bin',owner_uid=1000,public_key=settings.public_key,installation=settings.installation,key_id=settings.key_id,commitment=settings.commitment)
pool.open(wait=False)
try:
 publisher=HostPublisher(pool,protected,key)
 publisher.startup()
 head=publisher.once()
 if head.sequence!=0:raise RuntimeError('retirement_install_non_genesis_authority')
 print(module.json.dumps({'status':'genesis_acknowledged','sequence':head.sequence}))
finally:
 pool.close(timeout=3)
"""
    return (prefix + suffix).encode()
