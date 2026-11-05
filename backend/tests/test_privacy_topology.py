"""Read-only activation probes reject managers, replicas and changed commands."""

import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[2] / "tools/checks/privacy_topology.py"
SPEC = importlib.util.spec_from_file_location("privacy_topology_probe", PATH)
topology = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(topology)
IMAGE = "sha256:" + "a" * 64


class TopologyTests(unittest.TestCase):
    def metadata(self):
        return {
            "image": IMAGE,
            "entrypoint": None,
            "cmd": topology.CMD,
            "init": True,
            "pid": 100,
            "running": True,
            "project": "bank-ai",
            "service": "backend",
        }

    def test_exact_current_container_command_is_required(self):
        topology.validate_container(self.metadata(), IMAGE)
        for key, value in (
            ("image", "sha256:" + "b" * 64),
            ("entrypoint", ["gunicorn"]),
            ("cmd", topology.CMD + ["--workers", "2"]),
            ("init", False),
            ("service", "other"),
            ("running", False),
        ):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                topology.validate_container({**self.metadata(), key: value}, IMAGE)

    def test_one_uvicorn_direct_child_of_docker_init_is_supported(self):
        raw = b"PID PPID COMMAND COMMAND\n100 1 docker-init /sbin/docker-init -- uvicorn main:app --host 127.0.0.1 --port 8000\n101 100 uvicorn /usr/local/bin/python /usr/local/bin/uvicorn main:app --host 127.0.0.1 --port 8000\n"
        self.assertEqual(topology.processes(raw, 100)["web_processes"], 1)
        for replacement in (b"--port 8000 --workers 2", b"--port 8000 --reload"):
            with self.subTest(replacement=replacement), self.assertRaises(RuntimeError):
                topology.processes(raw.replace(b"--port 8000", replacement), 100)

    def test_second_worker_or_unexpected_parent_is_closed(self):
        raw = b"PID PPID COMMAND COMMAND\n100 1 docker-init /sbin/docker-init -- uvicorn main:app --host 127.0.0.1 --port 8000\n101 100 uvicorn /usr/local/bin/uvicorn main:app --host 127.0.0.1 --port 8000\n"
        with self.assertRaises(RuntimeError):
            topology.processes(
                raw
                + b"102 100 uvicorn /usr/local/bin/uvicorn main:app --host 127.0.0.1 --port 8000\n",
                100,
            )
        with self.assertRaises(RuntimeError):
            topology.processes(raw.replace(b"101 100", b"101 99"), 100)


if __name__ == "__main__":
    unittest.main()
