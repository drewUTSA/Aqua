"""Exercise the two built images under the shipping Compose hardening in a private namespace."""

import argparse
import json
from pathlib import Path
import secrets
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def docker(*arguments, timeout=60):
    result = subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return result.stdout.strip()


def process_flags(status, uid):
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    assert fields["Uid"].split() == [uid] * 4 and fields["Gid"].split() == [uid] * 4
    assert fields["NoNewPrivs"].strip() == "1"
    assert all(int(fields[key], 16) == 0 for key in ("CapEff", "CapPrm", "CapBnd"))


def application_status(identifier, name):
    if name == "backend":
        return json.loads(
            docker(
                "exec",
                identifier,
                "python",
                "-c",
                "import json; from pathlib import Path; rows=[]\n"
                "for entry in Path('/proc').iterdir():\n"
                " if not entry.name.isdecimal(): continue\n"
                " try:\n"
                "  argv=(entry/'cmdline').read_bytes().split(b'\\0')\n"
                "  if any(part.rsplit(b'/',1)[-1]==b'uvicorn' for part in argv[:2]):\n"
                "   rows.append((entry/'status').read_text())\n"
                " except FileNotFoundError: continue\n"
                "print(json.dumps(rows))",
            )
        )
    return docker(
        "exec",
        identifier,
        "sh",
        "-c",
        "for entry in /proc/[0-9]*/comm; do "
        'read -r command < "$entry" || continue; '
        'if [ "$command" = nginx ]; then cat "${entry%/comm}/status"; printf "\\n"; fi; done',
    ).split("\n\n")


def verify(backend, frontend):
    project = "aqua-hardening-" + secrets.token_hex(8)
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        base = directory / "compose.yml"
        base.write_bytes((ROOT / "docker-compose.yml").read_bytes())
        (directory / ".env").write_text("", encoding="ascii")
        resolved = json.loads(
            docker("compose", "-f", str(base), "config", "--format", "json")
        )
        services = resolved["services"]
        assert set(services) == {"backend", "frontend"}
        fixture = {}
        for name, image in (("backend", backend), ("frontend", frontend)):
            source = services[name]
            expected_user = "101:101" if name == "frontend" else "1000:1000"
            # Refuse elevation before creating a fixture. Do not silently drop
            # security-affecting overrides from the shipping Compose service.
            assert source.get("privileged", False) is False
            assert not source.get("cap_add")
            assert source.get("user", expected_user) == expected_user
            assert source["cap_drop"] == ["ALL"] and source["read_only"] is True
            assert source["security_opt"] == ["no-new-privileges:true"]
            mounts = {entry.split(":", 1)[0] for entry in source["tmpfs"]}
            assert mounts == (
                {"/tmp", "/var/cache/nginx"} if name == "frontend" else {"/tmp/aqua"}
            )
            assert source["network_mode"] == "host"
            assert (
                docker("image", "inspect", image, "--format", "{{.Config.User}}")
                == expected_user
            )
            fixture[name] = {
                key: source[key]
                for key in (
                    "read_only",
                    "cap_drop",
                    "security_opt",
                    "tmpfs",
                    "healthcheck",
                )
            }
            fixture[name]["image"] = image
            fixture[name]["network_mode"] = (
                "none" if name == "backend" else "service:backend"
            )
            fixture[name].update(
                mem_limit="1g" if name == "backend" else "512m",
                memswap_limit="1g" if name == "backend" else "512m",
                cpus=2,
                pids_limit=256,
                logging={
                    "driver": "local",
                    "options": {"max-size": "2m", "max-file": "2"},
                },
            )
            if "init" in source:
                fixture[name]["init"] = source["init"]
        tmpdir = services["backend"]["environment"]["TMPDIR"]
        assert tmpdir == "/tmp/aqua"
        fixture["backend"]["environment"] = {"TMPDIR": tmpdir}
        isolated = directory / "fixture.json"
        isolated.write_text(json.dumps({"services": fixture}), encoding="ascii")
        compose = ("compose", "-p", project, "-f", str(isolated))
        try:
            docker(
                *compose,
                "up",
                "--no-build",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "40",
            )
            for name, uid in (("backend", "1000"), ("frontend", "101")):
                identifier = docker(*compose, "ps", "-q", name)
                actual = json.loads(docker("inspect", identifier))[0]
                assert actual["State"]["Health"]["Status"] == "healthy"
                assert actual["HostConfig"]["ReadonlyRootfs"] is True
                assert actual["HostConfig"]["Memory"] == (
                    1 << 30 if name == "backend" else 512 << 20
                )
                assert actual["HostConfig"]["NanoCpus"] == 2_000_000_000
                assert actual["HostConfig"]["PidsLimit"] == 256
                if name == "backend":
                    assert (
                        actual["HostConfig"]["Init"] is services[name]["init"] is True
                    )
                status = docker("exec", identifier, "cat", "/proc/1/status")
                process_flags(status, uid)
                processes = application_status(identifier, name)
                assert processes and all(status.strip() for status in processes)
                for status in processes:
                    process_flags(status, uid)
                mounts = docker("exec", identifier, "cat", "/proc/mounts").splitlines()
                assert any(
                    line.split()[1] == "/" and "ro" in line.split()[3].split(",")
                    for line in mounts
                )
                scratch = tmpdir if name == "backend" else "/tmp"
                assert any(line.split()[1:3] == [scratch, "tmpfs"] for line in mounts)
                if name == "backend":
                    assert (
                        docker(
                            "exec",
                            identifier,
                            "python",
                            "-c",
                            "from tempfile import TemporaryFile; from pathlib import Path; "
                            "assert Path('/tmp/requirements-runtime.lock').is_file(); "
                            "f = TemporaryFile(); f.write(b'synthetic'); f.close(); "
                            "print('ok')",
                        )
                        == "ok"
                    )
            # Use the actual stock service entry points with the same private loopback.
            site = docker(
                *compose,
                "exec",
                "-T",
                "frontend",
                "wget",
                "-qO-",
                "http://127.0.0.1:5173/",
            )
            assert 'id="root"' in site
            health = docker(
                *compose,
                "exec",
                "-T",
                "frontend",
                "wget",
                "-qO-",
                "http://127.0.0.1:5173/api/health",
            )
            assert json.loads(health)["status"] == "ok"
            assert (
                'server.listen(5173, "127.0.0.1");'
                in (ROOT / "frontend/scripts/dev.mjs").read_text()
            )
        finally:
            docker(*compose, "down", "--volumes", "--timeout", "5")
            assert not docker(
                "ps", "-aq", "--filter", "label=com.docker.compose.project=" + project
            )
    print(
        "Passed both non-root read-only processes, kernel flags, image health, website and API; fixture removed."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--frontend", required=True)
    inputs = parser.parse_args()
    verify(inputs.backend, inputs.frontend)
