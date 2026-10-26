"""No Docker/provider calls: prove host launcher admission and cleanup fences."""

import base64
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from ops.accountmail import launch as launcher
from ops.accountmail import docker_worker

IDENT = "a" * 64
IMAGE = "sha256:" + "b" * 64
NONCE = "c" * 32


def environment(**changes):
    env = {
        "ACCOUNT_MAIL_ENABLED": "true",
        "ACCOUNT_MAIL_WORKER_ENABLED": "true",
        "ACCOUNT_MAIL_OUTBOX_KEY": base64.urlsafe_b64encode(b"K" * 32).decode(),
        "ACCOUNT_PUBLIC_ORIGIN": "https://aqua-ai.us",
        "RESEND_API_KEY": "re_synthetic_fixture_key",
        "APP_STORAGE_ENABLED": "true",
        "APP_DATABASE_URL": "postgresql://aqua_app_runtime:"
        + "f" * 43
        + "@/aqua_app?host=/run/aqua-app-db&port=5432&sslmode=disable",
        "APP_DB_POOL_SIZE": "1",
        "APP_DB_MAX_WAITING": "1",
        "APP_DB_WAIT_SECONDS": "2",
    }
    env.update(changes)
    return ("".join(key + "=" + value + "\n" for key, value in env.items())).encode()


@pytest.fixture
def private(tmp_path):
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    directory = parent / "mail"
    directory.mkdir(mode=0o700)
    write_environment(directory, environment())
    return directory


def write_environment(directory, raw):
    path = directory / "worker.env"
    path.write_bytes(raw)
    path.chmod(0o600)


def test_environment_file_is_exactly_scoped_and_pauses_without_losing_secrets(private):
    launcher.private_directory(private)
    raw, enabled = launcher.read_environment(private)
    assert raw == environment() and enabled
    write_environment(private, environment(ACCOUNT_MAIL_WORKER_ENABLED="false"))
    assert launcher.read_environment(private) == (
        environment(ACCOUNT_MAIL_WORKER_ENABLED="false"),
        False,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"DATABASE_URL": "unrelated-business-database"},
        {"GOOGLE_CLIENT_ID": "unrelated-google-client"},
        {"ACCOUNT_PUBLIC_ORIGIN": "https://elsewhere.invalid"},
        {"ACCOUNT_MAIL_OUTBOX_KEY": "not-base64"},
        {"ACCOUNT_MAIL_OUTBOX_KEY": base64.urlsafe_b64encode(b"K" * 31).decode()},
        {"RESEND_API_KEY": "invalid-provider-key"},
        {"APP_DB_POOL_SIZE": "2"},
        {"APP_DB_MAX_WAITING": "8"},
        {"APP_DB_WAIT_SECONDS": "5"},
        {"APP_STORAGE_ENABLED": "false"},
        {"ACCOUNT_MAIL_ENABLED": "TRUE"},
        {
            "APP_DATABASE_URL": "postgresql://aqua_app_runtime:fixture@127.0.0.1/aqua_app"
        },
    ],
)
def test_unreviewed_keys_origins_credentials_and_resource_bounds_fail_closed(
    private, changes
):
    write_environment(private, environment(**changes))
    with pytest.raises(launcher.Unavailable, match="invalid_worker_environment"):
        launcher.read_environment(private)


@pytest.mark.parametrize(
    "raw",
    [
        b"x" * 16385,
        environment() + b"ACCOUNT_MAIL_ENABLED=true\n",
        environment().replace(b"\n", b"\r\n"),
        environment() + b"\0",
        environment() + b"\v",
        environment().replace(b"APP_DB_POOL_SIZE=1\n", b""),
        environment().replace(b"APP_DB_POOL_SIZE=1", b"export APP_DB_POOL_SIZE=1"),
    ],
)
def test_env_file_is_not_shell_dotenv_or_duplicate_override_code(private, raw):
    write_environment(private, raw)
    with pytest.raises(launcher.Unavailable):
        launcher.read_environment(private)


def test_environment_and_lock_must_be_owner_only_regular_unlinked_files(private):
    path = private / "worker.env"
    path.chmod(0o640)
    with pytest.raises(launcher.Unavailable):
        launcher.read_environment(private)
    path.chmod(0o600)
    os.link(path, private / "second-link")
    with pytest.raises(launcher.Unavailable):
        launcher.read_environment(private)
    lock = private / ".launcher.lock"
    lock.write_bytes(b"")
    lock.chmod(0o644)
    with pytest.raises(launcher.Unavailable):
        with launcher.singleton(private):
            pytest.fail("unsafe lock admitted")


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_environment_special_file_is_rejected_without_following_or_blocking(
    private, kind
):
    path = private / "worker.env"
    path.unlink()
    if kind == "symlink":
        path.symlink_to(private / ".elsewhere")
    else:
        os.mkfifo(path, 0o600)
    with pytest.raises((OSError, launcher.Unavailable)):
        launcher.read_environment(private)


def test_private_parent_permissions_and_symlinks_are_rejected(private):
    private.parent.chmod(0o750)
    with pytest.raises(launcher.Unavailable):
        launcher.private_directory(private)
    private.parent.chmod(0o700)
    alias = private.parent / "alias"
    alias.symlink_to(private, target_is_directory=True)
    with pytest.raises(launcher.Unavailable):
        launcher.private_directory(alias)


def test_nonblocking_singleton_prevents_overlap_and_releases_on_exit(private):
    with launcher.singleton(private) as first:
        assert first
        with launcher.singleton(private) as second:
            assert not second
    with launcher.singleton(private) as recovered:
        assert recovered


def test_sealed_memfd_snapshot_is_readable_but_cannot_be_modified():
    raw = environment()
    with launcher.sealed_environment(raw) as fd:
        assert os.pread(fd, len(raw), 0) == raw
        with pytest.raises(PermissionError):
            os.write(fd, b"mutated")
    with pytest.raises(OSError):
        os.read(fd, 1)


class FakeDocker:
    def __init__(self):
        self.calls = []
        self.cleaned = []
        self.leftover = False
        self.clean_ok = True
        self.failure = False
        self.output = {"status": "idle"}

    def ids(self, *args, **kwargs):
        return [IDENT] if self.leftover else []

    def owned(self, nonce, **kwargs):
        return IDENT

    def clean(self, nonce, ident):
        self.cleaned.append((nonce, ident))
        return self.clean_ok

    def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if args[:2] == ("image", "inspect"):
            return IMAGE
        if args[:2] == ("volume", "inspect"):
            return launcher.SOCKET_VOLUME
        if args[:2] == ("container", "create"):
            assert os.pread(kwargs["fd"], 16384, 0) == environment()
            return IDENT
        if self.failure:
            raise launcher.Unavailable("docker_timeout")
        return json.dumps(self.output)


def install_fake(monkeypatch, fake):
    monkeypatch.setattr(launcher, "host_ready", lambda: None)
    monkeypatch.setattr(launcher, "Docker", lambda: fake)
    monkeypatch.setattr(launcher.secrets, "token_hex", lambda count: NONCE)


def test_one_job_uses_pinned_image_scoped_environment_and_container_fences(
    private, monkeypatch
):
    fake = FakeDocker()
    install_fake(monkeypatch, fake)
    assert launcher.launch(private) == "idle"
    create = next(args for args, _ in fake.calls if args[:2] == ("container", "create"))
    for fence in [
        "--pull=never",
        "--network=bridge",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--memory=128m",
        "--cpus=1",
        "--pids-limit=32",
        "--user=1000:1000",
        "--log-driver=none",
        "--restart=no",
    ]:
        assert fence in create
    assert create[-4:] == ("--entrypoint=python", IMAGE, "-m", "auth.mailworker")
    assert "type=volume,src=aqua_app_sockets,dst=/run/aqua-app-db,readonly" in create
    assert not any("re_synthetic_fixture_key" in arg for arg in create)
    assert fake.cleaned == [(NONCE, IDENT)]
    start = next(
        kwargs for args, kwargs in fake.calls if args[:2] == ("container", "start")
    )
    assert start["timeout"] == 35


def test_paused_worker_performs_no_docker_work(private, monkeypatch):
    write_environment(private, environment(ACCOUNT_MAIL_WORKER_ENABLED="false"))
    monkeypatch.setattr(
        launcher, "host_ready", lambda: pytest.fail("paused worker used Docker")
    )
    assert launcher.launch(private) == "disabled"


def test_managed_leftover_blocks_new_attempt_instead_of_overlapping(
    private, monkeypatch
):
    fake = FakeDocker()
    fake.leftover = True
    install_fake(monkeypatch, fake)
    with pytest.raises(launcher.Unavailable, match="leftover_worker"):
        launcher.launch(private)
    assert not fake.calls and not fake.cleaned


@pytest.mark.parametrize("fault", ["timeout", "unexpected_output", "cleanup"])
def test_failed_or_hung_work_always_requires_verified_cleanup(
    private, monkeypatch, fault
):
    fake = FakeDocker()
    if fault == "timeout":
        fake.failure = True
    elif fault == "unexpected_output":
        fake.output = {"status": "idle", "private": "PRIVATE_OUTPUT_CANARY"}
    else:
        fake.clean_ok = False
    install_fake(monkeypatch, fake)
    with pytest.raises(launcher.Unavailable):
        launcher.launch(private)
    assert fake.cleaned == [(NONCE, IDENT)]


@pytest.mark.parametrize("remove_fails", [True, False])
def test_lost_cleanup_response_is_resolved_only_by_independent_absence(
    monkeypatch, remove_fails
):
    docker = launcher.Docker()
    monkeypatch.setattr(docker, "owned", lambda *args, **kwargs: IDENT)
    monkeypatch.setattr(docker, "ids", lambda *args, **kwargs: [])
    calls = []

    def call(*args, **kwargs):
        calls.append(args)
        if remove_fails:
            raise launcher.Unavailable("docker_timeout")
        return ""

    monkeypatch.setattr(docker, "call", call)
    assert docker.clean(NONCE, IDENT)
    assert calls == [("container", "rm", "--force", IDENT)]


def test_unknown_ownership_or_unobserved_timed_out_create_is_never_deleted(monkeypatch):
    docker = launcher.Docker()
    monkeypatch.setattr(docker, "owned", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        docker, "call", lambda *args, **kwargs: pytest.fail("unowned delete")
    )
    assert not docker.clean(NONCE, None)
    monkeypatch.setattr(docker, "owned", lambda *args, **kwargs: "d" * 64)
    assert not docker.clean(NONCE, IDENT)


def test_cleanup_remaining_container_is_failure(monkeypatch):
    docker = launcher.Docker()
    monkeypatch.setattr(docker, "owned", lambda *args, **kwargs: IDENT)
    monkeypatch.setattr(docker, "call", lambda *args, **kwargs: "")
    monkeypatch.setattr(docker, "ids", lambda *args, **kwargs: [IDENT])
    assert not docker.clean(NONCE, IDENT)


@pytest.mark.parametrize("wrong", ["name", "purpose", "nonce"])
def test_cleanup_ownership_checks_exact_name_and_both_labels(monkeypatch, wrong):
    docker = launcher.Docker()
    monkeypatch.setattr(docker, "ids", lambda *args, **kwargs: [IDENT])
    name = "/" + launcher.NAME
    labels = {launcher.LABEL: launcher.PURPOSE, launcher.RUN_LABEL: NONCE}
    if wrong == "name":
        name = "/unrelated"
    elif wrong == "purpose":
        labels[launcher.LABEL] = "unrelated"
    else:
        labels[launcher.RUN_LABEL] = "unrelated"
    monkeypatch.setattr(
        docker,
        "call",
        lambda *args, **kwargs: "\n".join([IDENT, name, json.dumps(labels)]),
    )
    with pytest.raises(launcher.Unavailable):
        docker.owned(NONCE)


def test_docker_calls_ignore_ambient_context_proxy_and_credentials(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://unrelated.invalid:2375")
    monkeypatch.setenv("HTTPS_PROXY", "http://unrelated.invalid:8080")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(
            returncode=0, stdout=b"ok", stderr=b"PRIVATE_OUTPUT_CANARY"
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert launcher.Docker().call("info") == "ok"
    args, kwargs = calls[0]
    assert args[:3] == [
        "/usr/bin/docker",
        "--host=unix:///var/run/docker.sock",
        "--config=/nonexistent",
    ]
    assert kwargs["env"] == docker_worker.COMMAND_ENV
    assert not {"DOCKER_HOST", "HTTPS_PROXY", "RESEND_API_KEY"} & set(kwargs["env"])
    assert kwargs["timeout"] <= 8 and kwargs["stdin"] == subprocess.DEVNULL


def test_expired_launcher_deadline_performs_no_new_operation(monkeypatch):
    docker = launcher.Docker()
    docker.deadline = 0
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: pytest.fail("deadline ignored")
    )
    with pytest.raises(launcher.Unavailable):
        docker.call("info")


def test_top_level_never_reflects_child_output_secret_or_exception(monkeypatch, capsys):
    def fail():
        raise RuntimeError("PRIVATE_OUTPUT_CANARY")

    monkeypatch.setattr(launcher, "launch", fail)
    monkeypatch.setattr(launcher.signal, "signal", lambda *args: None)
    assert launcher.main() == 1
    captured = capsys.readouterr()
    assert captured.err == "" and "PRIVATE_OUTPUT_CANARY" not in captured.out
    assert json.loads(captured.out) == {
        "status": "unavailable",
        "detail": "account_mail_launcher_failed",
    }
