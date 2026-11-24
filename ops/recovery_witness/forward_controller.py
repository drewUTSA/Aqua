"""Require actual stopped writers and a fresh genesis before enabling forward enrollment."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

if not __package__ and Path(__file__).with_name("installation-sources.json").is_file():
    # When installed, this file sits beside the stock installer's pinned sources.
    import install
    import maintenance
    import operator_files as files
    from export_resources import Owned
    from installed_publisher import _deferred_cancellation
    from operator_scope import PRODUCTION, selected_scope
else:
    if not __package__:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ops.retirement import install, maintenance
    from ops.retirement import operator_files as files
    from ops.retirement.export_resources import Owned
    from ops.retirement.installed_publisher import _deferred_cancellation
    from ops.retirement.operator_scope import PRODUCTION, selected_scope


class Participant(Owned):
    purpose = "retirement-forward-enrollment"
    roles = frozenset({"inspect", "prepare", "activate"})

    def run(self, role, source):
        if role not in self.roles or role in self.attempted:
            raise ValueError("forward_role")
        self.attempted.append(role)
        self.uncertain.add(role)
        original = self.private / "host"
        mounts = [
            "--mount=type=bind,src="
            + str(original / name)
            + ",dst=/run/aqua-forward-input/"
            + name
            + ",readonly"
            for name in ("host.json", "publisher.json")
        ]
        if role == "inspect":
            mounts.append(
                "--tmpfs=/run/aqua-forward-output:rw,nosuid,nodev,noexec,size=4096,uid=1000,gid=1000,mode=0700"
            )
        else:
            mounts.append(
                "--mount=type=bind,src="
                + str(original / "forward-v1")
                + ",dst=/run/aqua-forward-output"
            )
        identifier = self.remember(
            role,
            self.command(
                "container",
                "create",
                "--pull=never",
                "--name=" + self.name + "-" + role,
                "--label=io.aqua.run=" + self.name,
                "--label=io.aqua.purpose=" + self.purpose,
                *self.scope.child_labels(),
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                "--user=1000:1000",
                "--memory=160m",
                "--memory-swap=160m",
                "--cpus=1",
                "--pids-limit=32",
                "--restart=no",
                "--log-driver=none",
                "--no-healthcheck",
                "--stop-timeout=1",
                "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=1048576",
                "--tmpfs=/run/aqua-forward-input:rw,nosuid,nodev,noexec,size=4096,uid=1000,gid=1000,mode=0700",
                "--mount=type=bind,src="
                + str(self.private / "authority")
                + ",dst=/run/aqua-forward-authority,readonly",
                "--mount=type=volume,src="
                + self.socket
                + ",dst=/run/aqua-app-db,readonly",
                *mounts,
                "--entrypoint=python",
                self.profile["runtime_image"],
                "-E",
                "-s",
                "-B",
                "-c",
                source,
            )
            .decode()
            .strip(),
        )
        if identifier != self.inspect(role):
            raise RuntimeError("forward_child_identity")
        self.uncertain.discard(role)
        reply = self.command("start", "--attach", identifier, maximum_seconds=40)
        state = self.command(
            "inspect",
            identifier,
            "--format={{json .State.Running}}\n{{json .State.ExitCode}}",
        )
        if state.splitlines() != [b"false", b"0"]:
            raise RuntimeError("forward_child_failed")
        result = json.loads(reply)
        if type(result) is not dict:
            raise RuntimeError("forward_child_reply")
        return result


def program(mode, envelope, cache, source):
    setup = "import sys, types\n"
    for name, raw in (
        ("host", cache["retirement_host.py"]),
        ("files", cache["operator_files.py"]),
        ("forward", source),
    ):
        setup += f"{name}=types.ModuleType({name!r});{name}.__file__='/app/ops/retirement/{name}.py';sys.modules[{name!r}]={name}\nexec(compile({raw!r},{name!r},'exec'),{name}.__dict__)\n"
    return (
        setup
        + f"import json;print(json.dumps(forward.operate({mode!r},{envelope!r},host,files)))"
    )


def execute(mode, envelope_sha, scope=PRODUCTION):
    if mode not in ("prepare", "activate") or not re.fullmatch(
        "[a-f0-9]{64}", envelope_sha
    ):
        raise ValueError("forward_scope")
    scope.validate()
    root = files.PRIVATE if scope is PRODUCTION else scope.private
    envelope = files.pinned(
        root / "operator" / ("forward-" + mode + ".json"), envelope_sha
    )
    names = {
        "installation_id",
        "identity_key_id",
        "key_commitment",
        "public_key",
        "genesis_sha256",
        "witness_public_key",
        "runtime_image",
        "source_sha256",
        "plan_sha256",
        "legacy_profile_sha256",
        "helper_sha256",
    }
    if mode == "activate":
        names.add("service_public_key")
    if set(envelope) != names or any(type(s) is not str for s in envelope.values()):
        raise ValueError("forward_public_envelope")
    for k, v in envelope.items():
        rule = (
            r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
            if k.endswith("_id")
            else r"sha256:[a-f0-9]{64}" if k == "runtime_image" else r"[a-f0-9]{64}"
        )
        if not re.fullmatch(rule, v):
            raise ValueError("forward_public_pin")
    path = Path(__file__).resolve().with_name("forward_source.py")
    if path.resolve(strict=True) != path:
        raise ValueError("forward_helper_path")
    with path.open("rb") as handle:
        source = handle.read(32769)
    if (
        len(source) > 32768
        or hashlib.sha256(source).hexdigest() != envelope["helper_sha256"]
    ):
        raise ValueError("forward_helper_pin")
    legacy = files.pinned(
        root / "host/publisher.json", envelope["legacy_profile_sha256"]
    )
    cache = install.sources(legacy["host_code_manifest_sha256"])
    with (
        _deferred_cancellation() as cancelled,
        maintenance.Hold(envelope["plan_sha256"], scope=scope) as held,
    ):
        held.require(10)
        if (held.value["runtime_image"], held.value["source_sha256"]) != (
            envelope["runtime_image"],
            envelope["source_sha256"],
        ):
            raise ValueError("forward_host_plan")
        participant = Participant(envelope, scope=scope)
        try:
            before = participant.run(
                "inspect", program("inspect", envelope, cache, source)
            )
            if before != {
                "status": "fresh_genesis_verified",
                "genesis_sha256": envelope["genesis_sha256"],
            }:
                raise ValueError("forward_freshness_check")
            cancelled()
            held.require(10)
            directory = root / "host/forward-v1"
            if mode == "prepare":
                directory.mkdir(mode=0o700)
                fd = os.open(
                    directory.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                )
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            files.directory(directory)
            answer = participant.run(mode, program(mode, envelope, cache, source))
            fields = (
                {"service_public_key", "signed_genesis"}
                if mode == "prepare"
                else {"witness_sha256", "publisher_profile_sha256", "genesis_sha256"}
            )
            status = (
                "service_key_prepared"
                if mode == "prepare"
                else "witness_verified_writers_still_stopped"
            )
            if (
                set(answer) != {"status"} | fields
                or answer["status"] != status
                or any(
                    type(answer[k]) is not str
                    or not re.fullmatch(
                        "[a-f0-9]{416}" if k == "signed_genesis" else "[a-f0-9]{64}",
                        answer[k],
                    )
                    for k in fields
                )
            ):
                raise RuntimeError("forward_public_output")
            held.require(10)
            cancelled()
            return answer
        finally:
            participant.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "activate"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--envelope-sha256")
    parser.add_argument("--qa-run")
    parser.add_argument("--private-preview", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print('{"status":"prepared_only","writes":0,"private_reads":0}')
        return
    scope = selected_scope(args.qa_run, args.private_preview)
    try:
        print(json.dumps(execute(args.mode, args.envelope_sha256, scope)))
    except Exception:
        print('{"status":"forward_enrollment_unavailable","writers_resumed":false}')
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
