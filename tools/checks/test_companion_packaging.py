"""Source-only companion package and nginx guards, outside backend fixtures."""

import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULES = {
    "__init__.py",
    "application.py",
    "choices.py",
    "context.py",
    "data.py",
    "data_contract.py",
    "knowledge.py",
    "policy.py",
    "router.py",
    "service.py",
}


class CompanionPackaging(unittest.TestCase):
    def test_runtime_package_has_no_eval_model_or_transport_dependency_imports(self):
        files = sorted((ROOT / "backend/companion").glob("*.py"))
        self.assertEqual({path.name for path in files}, MODULES)
        forbidden = {
            "eval",
            "subprocess",
            "socket",
            "httpx",
            "requests",
            "google",
            "torch",
            "transformers",
            "ollama",
            "nl2sql.llm",
            "nl2sql.execute",
            "analysis.service",
        }
        for path in files:
            for node in ast.walk(ast.parse(path.read_text())):
                names = (
                    [entry.name for entry in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                )
                self.assertFalse(
                    any(
                        name == blocked or name.startswith(blocked + ".")
                        for name in names
                        for blocked in forbidden
                    ),
                    path.name,
                )

    def test_exact_runtime_python_allowlist_is_present_in_build_context(self):
        dockerfile = (ROOT / "backend/Dockerfile").read_text().splitlines()
        self.assertEqual(
            dockerfile.count(
                "COPY --chown=1000:1000 backend/companion/*.py ./companion/"
            ),
            1,
        )
        ignore = (ROOT / ".dockerignore").read_text().splitlines()
        self.assertEqual(ignore.count("!backend/companion/*.py"), 1)
        self.assertEqual(
            [line for line in ignore if line.startswith("!backend/companion")],
            ["!backend/companion/*.py"],
        )

    def test_companion_proxy_location_suppresses_private_access_logs(self):
        nginx = (ROOT / "frontend/nginx.conf").read_text()
        locations = re.findall(
            r"location ~ \^/api/v1/companion\(\?:/\|\$\) \{([^}]+)\}", nginx
        )
        self.assertEqual(len(locations), 1)
        self.assertEqual(
            [line.strip() for line in locations[0].splitlines() if line.strip()],
            [
                "access_log off;",
                "proxy_pass http://127.0.0.1:8000;",
                "proxy_read_timeout 5s;",
            ],
        )


if __name__ == "__main__":
    unittest.main()
