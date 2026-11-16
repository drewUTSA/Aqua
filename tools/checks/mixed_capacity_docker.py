"""Validate one platform-local daemon, then pin every Docker command to it."""

import json
import os
import subprocess
import sys
import time

SPECS = {
    "win32": (
        "C:/Program Files/Docker/Docker/resources/bin/docker.exe",
        "desktop-linux",
        "npipe:////./pipe/dockerDesktopLinuxEngine",
    ),
    "linux": ("/usr/bin/docker", "default", "unix:///var/run/docker.sock"),
}
OVERRIDES = frozenset(
    {
        "DOCKER_HOST",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
        "DOCKER_CONFIG",
        "DOCKER_API_VERSION",
    }
)


class LocalDocker:
    def __init__(self, *, environ=None, platform=None):
        env = dict(os.environ if environ is None else environ)
        selected = sys.platform if platform is None else platform
        if selected not in SPECS or any(name in env for name in OVERRIDES):
            raise ValueError("mixed_local_docker_environment_required")
        self.binary, self.context, self.endpoint = SPECS[selected]
        if env.get("DOCKER_CONTEXT") not in (None, self.context):
            raise ValueError("mixed_local_docker_context_required")
        self.environment = {"PATH": "/usr/bin:/bin"}
        for name in (
            "HOME",
            "USERPROFILE",
            "SystemRoot",
            "WINDIR",
            "PROGRAMDATA",
            "APPDATA",
            "LOCALAPPDATA",
        ):
            if name in env:
                self.environment[name] = env[name]
        self.metadata_environment = dict(self.environment)
        if "DOCKER_CONTEXT" in env:
            self.metadata_environment["DOCKER_CONTEXT"] = self.context
        self.verified = False

    def verify(self, deadline):
        def metadata(*arguments):
            remaining = min(15, deadline - time.monotonic())
            if remaining <= 0:
                raise TimeoutError("mixed_whole_fixture_deadline")
            result = subprocess.run(
                [self.binary, "context", *arguments],
                capture_output=True,
                timeout=remaining,
                env=self.metadata_environment,
            )
            if result.returncode or len(result.stdout) > 65536:
                raise ValueError("mixed_context_metadata_unverified")
            return result.stdout

        if metadata("show").strip() != self.context.encode():
            raise ValueError("mixed_local_docker_context_required")
        values = json.loads(metadata("inspect", self.context))
        if type(values) is not list or len(values) != 1 or type(values[0]) is not dict:
            raise ValueError("mixed_context_metadata_invalid")
        value = values[0]
        endpoint = value.get("Endpoints", {}).get("docker", {})
        if (
            value.get("Name") != self.context
            or type(endpoint) is not dict
            or endpoint.get("Host") != self.endpoint
            or endpoint.get("SkipTLSVerify", False) is not False
            or value.get("TLSMaterial") != {}
        ):
            raise ValueError("mixed_local_docker_endpoint_required")
        self.verified = True

    def capture(self, *arguments, data=None, timeout=60):
        if not self.verified:
            raise ValueError("mixed_transport_not_verified")
        # Explicit host wins over context files; no Docker environment selector,
        # TLS certificate override or remote context can redirect cleanup.
        return subprocess.run(
            [self.binary, "--host", self.endpoint, "--tls=false", *arguments],
            input=data,
            capture_output=True,
            timeout=timeout,
            env=self.environment,
        )

    def execute(self, *arguments, data=None, timeout=60):
        result = self.capture(*arguments, data=data, timeout=timeout)
        if result.returncode:
            raise RuntimeError("mixed_fixed_docker_operation_failed")
        return result.stdout
