"""Read-only P11 activation topology proof; never edits flags or starts services."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

CMD = ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]
ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/proc/self/fd",
    "DOCKER_CONFIG": "/proc/self/fd",
}
ENV_PROGRAM = """import json,os
expected={'APP_STORAGE_ENABLED':'true','APP_DB_POOL_SIZE':'4','WEB_CONCURRENCY':'1','UVICORN_WORKERS':'1','UVICORN_RELOAD':'false','GUNICORN_CMD_ARGS':'','SERVER_SOFTWARE':''}
defaults={**expected,'APP_STORAGE_ENABLED':'false'}
flag=os.environ.get('PRIVATE_DATA_EXPORT_ENABLED','false')
print(json.dumps({'valid':{name:os.environ.get(name,defaults[name])==value for name,value in expected.items()},'activation_flag':flag if flag in ('true','false') else 'invalid'}))
"""


def require(value, code):
    if not value:
        raise RuntimeError(code)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def docker(*args):
    result = subprocess.run(
        ["/usr/bin/docker", "--host=unix:///var/run/docker.sock", *args],
        capture_output=True,
        timeout=10,
        env=ENV,
    )
    require(
        result.returncode == 0 and len(result.stdout) <= 1048576,
        "topology_probe_unavailable",
    )
    return result.stdout


def command(value):
    values = shlex.split(value)
    if values and Path(values[0]).name in {"python", "python3", "python3.12"}:
        values = values[1:]
    if values:
        values[0] = Path(values[0]).name
    return values


def processes(raw, init_pid):
    """Inspect only process metadata in RAM; never emit raw args or commands."""
    lines = raw.decode("utf-8", errors="strict").splitlines()
    require(1 < len(lines) <= 257, "backend_process_inventory_bound")
    workers, initializers = [], []
    for line in lines[1:]:
        fields = line.split(None, 3)
        require(
            len(fields) == 4 and fields[0].isdigit() and fields[1].isdigit(),
            "backend_process_inventory_invalid",
        )
        pid, parent = int(fields[0]), int(fields[1])
        executable = fields[2]
        arguments = command(fields[3])
        if arguments == CMD and executable in {
            "python",
            "python3",
            "python3.12",
            "uvicorn",
        }:
            workers.append((pid, parent))
        elif executable == "docker-init" and arguments == ["docker-init", "--", *CMD]:
            initializers.append(pid)
        else:
            raise RuntimeError("unexpected_backend_process")
    require(
        len(workers) == len(initializers) == 1
        and initializers[0] == init_pid
        and workers[0][1] == init_pid,
        "one_direct_uvicorn_process_required",
    )
    return {"web_processes": 1, "backend_processes": 2, "init_verified": True}


def validate_container(metadata, expected_image):
    require(
        re.fullmatch(r"sha256:[a-f0-9]{64}", expected_image),
        "reviewed_backend_image_required",
    )
    require(
        set(metadata)
        == {
            "image",
            "entrypoint",
            "cmd",
            "init",
            "pid",
            "running",
            "project",
            "service",
        },
        "backend_metadata_contract_changed",
    )
    require(
        metadata["image"] == expected_image
        and metadata["entrypoint"] in (None, [])
        and metadata["cmd"] == CMD
        and metadata["init"] is True
        and metadata["running"] is True
        and type(metadata["pid"]) is int
        and metadata["pid"] > 1
        and metadata["project"] == "bank-ai"
        and metadata["service"] == "backend",
        "reviewed_single_backend_command_required",
    )


def probe(image):
    ids = (
        docker(
            "ps",
            "--quiet",
            "--no-trunc",
            "--filter",
            "label=com.docker.compose.project=bank-ai",
            "--filter",
            "label=com.docker.compose.service=backend",
        )
        .decode()
        .split()
    )
    require(
        len(ids) == 1 and re.fullmatch(r"[a-f0-9]{64}", ids[0]),
        "exactly_one_backend_container_required",
    )
    template = '{"image":{{json .Image}},"entrypoint":{{json .Config.Entrypoint}},"cmd":{{json .Config.Cmd}},"init":{{json .HostConfig.Init}},"pid":{{json .State.Pid}},"running":{{json .State.Running}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}}}'
    metadata_raw = docker("container", "inspect", ids[0], "--format", template)
    metadata = json.loads(metadata_raw)
    validate_container(metadata, image)
    raw = docker("top", ids[0], "-eo", "pid,ppid,comm,args")
    layout = processes(raw, metadata["pid"])
    # Fixed in-container program emits booleans for explicit nonsecret options;
    # it never reads .env files, DSNs, credentials or arbitrary environment keys.
    environment = json.loads(
        docker(
            "exec", "-w", "/app", ids[0], "python", "-E", "-s", "-B", "-c", ENV_PROGRAM
        )
    )
    require(
        set(environment) == {"valid", "activation_flag"}
        and len(environment["valid"]) == 7
        and all(value is True for value in environment["valid"].values())
        and environment["activation_flag"] in {"true", "false"},
        "single_process_runtime_configuration_required",
    )
    return {
        "status": "passed",
        "scope": "observed_supported_compose_backend_topology_only",
        "backend_image": image,
        "backend_container_id": ids[0],
        "backend_containers": 1,
        **layout,
        "activation_flag": environment["activation_flag"],
        "runtime_connections_planned": 8,
        "probe_connections_reserved": 2,
        "runtime_role_limit_required": 12,
        "container_metadata_sha256": digest(metadata_raw),
        "process_inventory_sha256": digest(raw),
        "configuration_probe_sha256": digest(ENV_PROGRAM.encode()),
        "private_values_emitted": False,
        "production_changed": False,
        "activation_authorized": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = probe(args.backend_image)
    except Exception as error:
        category = (
            str(error)
            if isinstance(error, RuntimeError)
            and re.fullmatch(r"[a-z0-9_]{1,96}", str(error))
            else "topology_probe_unavailable"
        )
        result = {
            "status": "failed",
            "category": category,
            "production_changed": False,
            "activation_authorized": False,
        }
    if args.output is not None:
        output = args.output.resolve()
        require(
            output.is_relative_to(Path("/srv/bank-ai/.check-results"))
            and not output.exists(),
            "fresh_owned_topology_receipt_required",
        )
        descriptor = os.open(
            output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w") as target:
            json.dump(result, target, indent=2)
            target.write("\n")
    print(json.dumps(result))
    raise SystemExit(result["status"] != "passed")
