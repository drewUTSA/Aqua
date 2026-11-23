"""Launch a disposable copy of Aqua from the extracted private Windows transfer."""

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
POSTGRES = (
    "postgres@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826"
)
LABEL = "io.aqua.presenter.session"
CONTEXT = ["docker", "--context", "desktop-linux"]
HBA = b"""local all postgres peer
host aqua_app aqua_app_migrator,aqua_app_runtime 127.0.0.1/32 scram-sha-256
host aqua_sales_demo aqua_sales_demo_reader 127.0.0.1/32 scram-sha-256
host all all 0.0.0.0/0 reject
host all all ::0/0 reject
"""


def docker(*args, data=None, check=True, timeout=120):
    result = subprocess.run(
        [*CONTEXT, *args], input=data, capture_output=True, timeout=timeout
    )
    if check and result.returncode:
        # Inputs, command details and Docker error streams can contain credentials.
        raise RuntimeError(f"Docker {args[0]} failed during {STAGE}")
    return result


def verify_engine():
    endpoint = docker(
        "context", "inspect", "desktop-linux", "--format", "{{.Endpoints.docker.Host}}"
    ).stdout.strip()
    if endpoint != b"npipe:////./pipe/dockerDesktopLinuxEngine":
        raise RuntimeError(
            "This launcher requires the local Docker Desktop Linux engine"
        )
    docker("info", "--format", "{{.OSType}}")


def cleanup(session):
    if not re.fullmatch("[0-9a-f]{24}", session):
        raise ValueError("Invalid presenter session ID")
    rows = (
        docker(
            "ps",
            "-a",
            "--no-trunc",
            "--filter",
            f"label={LABEL}={session}",
            "--format",
            "{{.Names}} {{.ID}}",
        )
        .stdout.decode()
        .splitlines()
    )
    containers = dict(row.split() for row in rows)
    failures = []
    for suffix in ("web", "api", "ollama", "pg"):
        container = containers.get(f"aqua-presenter-{session}-{suffix}")
        if container:
            try:
                docker("rm", "--force", "--volumes", container)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                failures.append(suffix)
    if failures:
        raise RuntimeError(
            "Docker could not remove these session containers: " + ", ".join(failures)
        )


def profile_path(session):
    if not re.fullmatch("[0-9a-f]{24}", session):
        raise ValueError("Invalid presenter session ID")
    return Path(tempfile.gettempdir()).resolve() / ("aqua-presenter-" + session)


@contextmanager
def new_profile(session):
    import msvcrt

    root = profile_path(session)
    root.mkdir(mode=0o700)
    try:
        with (root / "presenter.session").open("x+b") as lease:
            lease.write(session.encode())
            lease.flush()
            lease.seek(0)
            msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
            yield root / "profile"
    finally:
        remove_profile(session)


class ActiveProfile(RuntimeError):
    """The launcher or Firefox still owns this session."""


def remove_profile(session):
    import ctypes
    from ctypes import wintypes

    root = profile_path(session)
    if not root.exists():
        return
    marker = root / "presenter.session"
    try:
        owned = (
            marker.read_bytes() == session.encode()
            if marker.resolve(strict=True) == marker
            else False
        )
    except PermissionError:
        raise ActiveProfile(
            "Close the running presenter session before cleanup"
        ) from None
    if root.resolve(strict=True) != root or not owned:
        raise ValueError("Unrecognized temporary presenter directory")
    parent_lock = root / "profile" / "parent.lock"
    if parent_lock.exists():
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        open_file = kernel.CreateFileW
        open_file.restype = wintypes.HANDLE
        open_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        handle = open_file(str(parent_lock), 0x80000000, 0, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ActiveProfile("Close the dedicated Firefox window and repeat cleanup")
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
    shutil.rmtree(root)


def recover(session):
    try:
        remove_profile(session)
    except ActiveProfile:
        raise
    except OSError:
        cleanup(session)
        raise
    cleanup(session)


def require_archive(path, manifest):
    with path.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    if (
        digest != manifest[path.name]["sha256"]
        or path.stat().st_size != manifest[path.name]["bytes"]
    ):
        raise ValueError(f"Transfer file failed verification: {path.name}")


def images(web, shell):
    manifest = json.loads(web.read("MANIFEST.json"))["files"]
    backend = json.loads(web.read("backend/SOURCE.json"))["candidate_image"]
    front = json.loads(web.read("frontend/QUALIFICATION.json"))["shells"][shell]
    for member, image in (
        ("backend/schema10-backends.tar", backend),
        ("frontend/" + front["archive"]["file"], front["image"]),
    ):
        if not re.fullmatch("sha256:[a-f0-9]{64}", image):
            raise ValueError("Invalid image binding")
        blob = web.read(member)
        if hashlib.sha256(blob).hexdigest() != manifest[member]:
            raise ValueError("Packaged image digest mismatch")
        if docker("image", "inspect", image, check=False).returncode:
            docker("image", "load", data=blob)
        if (
            docker("image", "inspect", image, "--format", "{{.Id}}")
            .stdout.decode()
            .strip()
            != image
        ):
            raise ValueError("Incorrect loaded image")
    return backend, front["image"]


def write_private(container, fixed_path, data):
    if fixed_path not in {
        "/tmp/service.py",
        "/tmp/tls_edge.py",
        "/tmp/model_cache.py",
        "/tmp/service-env.json",
        "/var/lib/postgresql/data/pg_hba.conf",
    }:
        raise ValueError("Unexpected container file")
    docker(
        "exec",
        "-i",
        container,
        "sh",
        "-c",
        'umask 077; cat > "$1"',
        "sh",
        fixed_path,
        data=data,
    )


def wait_command(container, command):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if not docker(
                "exec", container, *command, check=False, timeout=12
            ).returncode:
                return
        except subprocess.TimeoutExpired:
            continue
        time.sleep(0.25)
    raise RuntimeError(f"Startup timed out during {STAGE}")


def install(transfer, shell, session, stack, model_cache, cpu):
    global STAGE
    from loopback import relay
    import model_cache as ollama

    manifest = json.loads((transfer / "MANIFEST.json").read_bytes())
    for name in ("web-and-backends.zip", "sales-data.zip"):
        require_archive(transfer / name, manifest)
    with zipfile.ZipFile(transfer / "web-and-backends.zip") as web:
        api_image, web_image = images(web, shell)
    if docker("image", "inspect", POSTGRES, check=False).returncode:
        print("Downloading the pinned PostgreSQL image for first use.", flush=True)
        docker("pull", POSTGRES, timeout=600)

    if model_cache is not None:
        STAGE = "verifying the selected local model"
        print("Checking the Qwen 3 8B manifest and model files.", flush=True)
        try:
            model_mounts = ollama.verified_mounts(model_cache)
        except (OSError, ValueError) as exc:
            raise ValueError(
                "Aqua needs the pinned qwen3:8b model. Follow the Ollama setup in presenter-demo/README.md."
            ) from exc
        if docker("image", "inspect", ollama.IMAGE, check=False).returncode:
            print(
                "Downloading the pinned Ollama service image for first use.", flush=True
            )
            docker("pull", ollama.IMAGE, timeout=900)

    def create(kind, image, options, command):
        name = f"aqua-presenter-{session}-{kind}"
        docker(
            "create",
            "--name",
            name,
            "--label",
            f"{LABEL}={session}",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "256",
            *options,
            image,
            *command,
        )
        docker("start", name)
        return name

    STAGE = "starting the isolated database"
    pg = create(
        "pg",
        POSTGRES,
        [
            "--network=none",
            "--user=999:999",
            "--memory=1g",
            "--cpus=2",
            "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=512m,uid=999,gid=999,mode=0700",
            "--tmpfs=/var/run/postgresql:rw,nosuid,nodev,size=16m,uid=999,gid=999",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=16m,mode=1777",
            "--entrypoint=sh",
        ],
        [
            "-c",
            "umask 077; head -c 48 /dev/urandom | base64 >/tmp/bootstrap; export POSTGRES_PASSWORD_FILE=/tmp/bootstrap; export POSTGRES_INITDB_ARGS='--auth-host=scram-sha-256 --auth-local=peer'; exec docker-entrypoint.sh postgres -c listen_addresses=127.0.0.1 -c log_statement=none",
        ],
    )
    wait_command(pg, ["pg_isready", "-h", "127.0.0.1", "-U", "postgres"])
    docker("exec", pg, "rm", "-f", "/tmp/bootstrap")
    STAGE = "restoring the two fictional databases"
    passwords = {
        role: secrets.token_hex(24)
        for role in ("migrator", "runtime", "backup", "reader")
    }
    variables = "".join(
        f"\\set {role}_password '{passwords[role]}'\n"
        for role in ("migrator", "runtime", "backup")
    )
    bootstrap = (HERE / "bootstrap.psql").read_bytes()
    psql = ["exec", "-i", pg, "psql", "-Xq", "-U", "postgres", "-v", "ON_ERROR_STOP=1"]
    docker(*psql, data=variables.encode() + bootstrap)
    reader = "aqua_sales_demo_reader"
    create_reader = f"CREATE ROLE {reader} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '{passwords['reader']}';"
    docker(*psql, data=create_reader.encode())
    with zipfile.ZipFile(transfer / "sales-data.zip") as sales:
        docker(
            "exec",
            "-i",
            pg,
            "pg_restore",
            "--create",
            "--exit-on-error",
            "-U",
            "postgres",
            "-d",
            "postgres",
            data=sales.read("sales-demo.dump"),
        )
    write_private(pg, "/var/lib/postgresql/data/pg_hba.conf", HBA)
    docker(*psql, data=b"SELECT pg_reload_conf();")
    shared = [
        "--network=container:" + pg,
        "--tmpfs=/tmp:rw,nosuid,nodev,size=64m,mode=1777",
    ]
    api = create(
        "api",
        api_image,
        [*shared, "--user=1000:1000", "--cpus=3", "--memory=2g", "--entrypoint=sleep"],
        ["infinity"],
    )
    if model_cache is not None:
        STAGE = "starting local Ollama (use --cpu if Docker has no NVIDIA GPU)"
        create(
            "ollama",
            ollama.IMAGE,
            [
                "--network=container:" + pg,
                "--user=1000:1000",
                "--cpus=4",
                "--memory=9g",
                "--tmpfs=/tmp:rw,exec,nosuid,nodev,size=512m,mode=1777",
                "--log-driver=none",
                "-e",
                "HOME=/tmp",
                "-e",
                "OLLAMA_MODELS=/models",
                "-e",
                "OLLAMA_HOST=127.0.0.1:11434",
                "-e",
                "OLLAMA_NO_CLOUD=1",
                "-e",
                "OLLAMA_GO_TEMPLATE=true",
                "-e",
                "OLLAMA_NUM_PARALLEL=1",
                "-e",
                "OLLAMA_MAX_LOADED_MODELS=1",
                "-e",
                "OLLAMA_KEEP_ALIVE=10m",
                *model_mounts,
                *([] if cpu else ["--gpus=all"]),
            ],
            ["serve"],
        )
        write_private(
            api, "/tmp/model_cache.py", (HERE / "model_cache.py").read_bytes()
        )
        client = ["python", "-B", "/tmp/model_cache.py"]
        wait_command(api, [*client, "probe"])
        STAGE = "loading the selected Qwen model"
        print("Loading Qwen into memory before opening the website.", flush=True)
        docker("exec", api, *client, "preload", timeout=190)
    port = stack.enter_context(relay(api))
    hostname = f"aqua-{session}.example.test"
    origin = f"https://{hostname}:{port}"

    def dsn(role, password, database):
        return (
            f"postgresql://{role}:{password}@127.0.0.1:5432/{database}?sslmode=disable"
        )

    env = {
        "APP_ORIGIN": origin,
        "APP_STORAGE_ENABLED": "true",
        "SESSION_SECRET": secrets.token_urlsafe(48),
        "APP_DATABASE_URL": dsn("aqua_app_runtime", passwords["runtime"], "aqua_app"),
        "DATABASE_URL": dsn(reader, passwords["reader"], "aqua_sales_demo"),
        "PASSWORD_AUTH_ENABLED": "true",
        "PASSWORD_REGISTRATION_ENABLED": "false",
        "ACCOUNT_MAIL_ENABLED": "false",
        "COMPANION_ENABLED": "true",
        "BANK_DEMO_ENABLED": "true",
        "BANK_DEMO_PERSONA": "analyst",
        "CONTEXT_NOTES_ENABLED": "true",
        "LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": ollama.MODEL,
        "LLM_FALLBACK": "off",
        "RETRIEVAL": "false",
    }
    STAGE = "creating the presenter account"
    config = {
        "environment": env,
        "migrator": dsn("aqua_app_migrator", passwords["migrator"], "aqua_app"),
        "mail_origin": "https://" + hostname,
    }
    write_private(api, "/tmp/service.py", (HERE / "service.py").read_bytes())
    credentials = json.loads(
        docker(
            "exec",
            "-i",
            api,
            "python",
            "-B",
            "/tmp/service.py",
            "provision",
            data=json.dumps(config).encode(),
        ).stdout
    )
    STAGE = "starting the Aqua service"
    write_private(api, "/tmp/service-env.json", json.dumps(env).encode())
    docker("exec", "-d", api, "python", "-B", "/tmp/service.py", "serve")
    wait_command(
        api,
        [
            "python",
            "-c",
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready',timeout=2).close()",
        ],
    )
    STAGE = "starting the private HTTPS website"
    web = create(
        "web",
        web_image,
        [
            *shared,
            "--user=101:101",
            "--memory=160m",
            "--cpus=1",
            "--tmpfs=/var/cache/nginx:rw,nosuid,nodev,size=8m,mode=0777",
            "--tmpfs=/var/run:rw,nosuid,nodev,size=1m,mode=0777",
        ],
        ["nginx", "-g", "daemon off;"],
    )
    write_private(api, "/tmp/tls_edge.py", (HERE / "tls_edge.py").read_bytes())
    edge = docker("exec", api, "python", "-B", "/tmp/tls_edge.py", hostname).stdout
    docker("exec", "-i", web, "tar", "-xf", "-", "-C", "/tmp", data=edge)
    docker("exec", web, "nginx", "-t", "-c", "/tmp/edge.conf")
    docker("exec", "-d", web, "nginx", "-c", "/tmp/edge.conf", "-g", "daemon off;")
    ca = docker("exec", api, "cat", "/tmp/fixture-ca.pem").stdout
    return hostname, origin, credentials, ca


def browser(profile, hostname, origin, ca):
    from profile_ca import FIREFOX, trust

    trust(profile, ca)
    prefs = {
        "network.dns.localDomains": hostname,
        "network.trr.mode": 5,
        "network.dns.disableIPv6": True,
        "network.proxy.type": 1,
        "network.proxy.http": "127.0.0.1",
        "network.proxy.http_port": 9,
        "network.proxy.ssl": "127.0.0.1",
        "network.proxy.ssl_port": 9,
        "network.proxy.no_proxies_on": hostname,
        "security.enterprise_roots.enabled": False,
        "signon.rememberSignons": False,
        "browser.shell.checkDefaultBrowser": False,
        "browser.startup.homepage_override.mstone": "ignore",
        "network.captive-portal-service.enabled": False,
        "datareporting.policy.dataSubmissionEnabled": False,
        "browser.newtabpage.enabled": False,
    }
    (profile / "user.js").write_text(
        "".join(
            f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k, v in prefs.items()
        ),
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [
            str(FIREFOX / "firefox.exe"),
            "-no-remote",
            "-profile",
            str(profile),
            origin + "/signin",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        code = process.wait()
        if code:
            raise RuntimeError(f"Firefox exited with status {code}")
    finally:
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True
            )
            process.wait(timeout=10)


STAGE = "checking prerequisites"


def main():
    global STAGE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell", choices=["opal", "legacy"], default="opal")
    parser.add_argument(
        "--model-cache",
        type=Path,
        metavar="FOLDER",
        help="enable local chat using the verified qwen3:8b files in this Ollama models folder",
    )
    parser.add_argument(
        "--cpu", action="store_true", help="use CPU inference with --model-cache"
    )
    parser.add_argument(
        "--transfer",
        type=Path,
        default=HERE.parent,
        help="extracted private employee transfer",
    )
    parser.add_argument(
        "--cleanup",
        metavar="SESSION",
        help="remove just this presenter's Docker containers",
    )
    args = parser.parse_args()
    if args.cpu and args.model_cache is None:
        parser.error("--cpu requires --model-cache")
    if os.name != "nt" or sys.maxsize <= 2**32:
        parser.error("Use 64-bit Windows Python and Firefox.")
    verify_engine()
    if args.cleanup:
        recover(args.cleanup)
        return
    from profile_ca import FIREFOX

    if not (FIREFOX / "firefox.exe").is_file():
        parser.error("Install 64-bit Mozilla Firefox in Program Files.")
    session = secrets.token_hex(12)
    print(f"Presenter session {session}", flush=True)
    print(
        "Verifying the transfer and preparing a fresh fictional workspace.", flush=True
    )
    try:
        with ExitStack() as stack:
            stack.callback(cleanup, session)
            profile = stack.enter_context(new_profile(session))
            hostname, origin, account, ca = install(
                args.transfer.resolve(),
                args.shell,
                session,
                stack,
                args.model_cache,
                args.cpu,
            )
            STAGE = "opening Firefox"
            print(
                f"Website {origin}\nEmail {account['email']}\nTemporary password {account['password']}",
                flush=True,
            )
            print(
                "Close the demo Firefox window or press Ctrl+C here to erase the session.",
                flush=True,
            )
            browser(profile, hostname, origin, ca)
    finally:
        print(
            f"Session {session} ended. If interrupted, run --cleanup {session} to check Docker cleanup.",
            flush=True,
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ) as exc:
        sys.exit(f"Presenter setup stopped during {STAGE}. {exc}")
