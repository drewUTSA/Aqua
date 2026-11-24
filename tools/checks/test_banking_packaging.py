"""Keep banking pure and limit runtime delivery to the reviewed report core."""

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULES = {
    "__init__.py",
    "catalog.py",
    "data.py",
    "knowledge.py",
    "proposals.py",
    "reports.py",
    "scope.py",
}
IMPORTS = {
    "dataclasses",
    "hashlib",
    "json",
    "re",
    "types",
    "unicodedata",
    "uuid",
    *(f"eval.banking.{name[:-3]}" for name in MODULES if name != "__init__.py"),
}
CONTEXT_ALLOWLIST = {
    "!backend/Dockerfile",
    "!backend/main.py",
    "!backend/auth/*.py",
    "!backend/nl2sql/*.py",
    "!backend/nl2sql/retrieval/*.py",
    "!backend/storage/*.py",
    "!backend/workspace/*.py",
    "!backend/analysis/*.py",
    "!backend/preferences/*.py",
    "!backend/account/*.py",
    "!backend/privacy/*.py",
    "!backend/retirement/*.py",
    "!backend/companion/*.py",
    "!backend/bank_demo/*.py",
    "!backend/result_companion/*.py",
    "!backend/context_notes/*.py",
    "!mcp_demo/__init__.py",
    "!mcp_demo/data.py",
    "!mcp_demo/finance.py",
    "!mcp_demo/protocol.py",
    "!mcp_demo/reports.py",
    "!mcp_demo/guidance.py",
    "!mcp_demo/web.py",
    "!mcp_demo/fixtures/bank.json",
    "!eval/__init__.py",
    "!eval/banking/__init__.py",
    "!eval/banking/catalog.py",
    "!eval/banking/data.py",
    "!eval/banking/knowledge.py",
    "!eval/banking/proposals.py",
    "!eval/banking/reports.py",
    "!eval/banking/scope.py",
    "!backend/migrations/*.sql",
    "!tools/checks/Dockerfile",
    "!tools/checks/requirements-runtime.lock",
    "!backend/auth/password_blocklist_*.txt",
    "!backend/auth/password_blocklist_provenance.json",
}


def imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (entry.name for entry in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


class BankingPackaging(unittest.TestCase):
    def test_offline_modules_allow_only_reviewed_pure_imports(self):
        files = sorted((ROOT / "eval/banking").glob("*.py"))
        self.assertEqual({path.name for path in files}, MODULES)
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            with self.subTest(module=path.name):
                self.assertLessEqual(set(imports(tree)), IMPORTS)
                self.assertFalse(
                    any(
                        isinstance(node, ast.Name)
                        and node.id
                        in {
                            "__builtins__",
                            "__import__",
                            "breakpoint",
                            "compile",
                            "eval",
                            "exec",
                            "globals",
                            "input",
                            "locals",
                            "open",
                        }
                        for node in ast.walk(tree)
                    )
                )

    def test_runtime_build_context_remains_closed_to_reviewed_sources(self):
        lines = [
            line.strip()
            for line in (ROOT / ".dockerignore").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(lines[0], "**")
        self.assertEqual(len(lines), len(CONTEXT_ALLOWLIST) + 1)
        self.assertEqual(set(lines[1:]), CONTEXT_ALLOWLIST)
        copies = [
            line.split()
            for line in (ROOT / "backend/Dockerfile").read_text().splitlines()
            if line.startswith("COPY ")
        ]
        self.assertTrue(copies)
        for instruction in copies:
            sources = [part for part in instruction[1:-1] if not part.startswith("--")]
            self.assertTrue(sources)
            self.assertTrue(all("!" + part in CONTEXT_ALLOWLIST for part in sources))

    def test_backend_runtime_does_not_import_offline_evaluation_packages(self):
        for path in sorted((ROOT / "backend").rglob("*.py")):
            if "tests" in path.relative_to(ROOT / "backend").parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            with self.subTest(module=path.relative_to(ROOT).as_posix()):
                self.assertFalse(
                    any(
                        name == "eval" or name.startswith("eval.")
                        for name in imports(tree)
                    )
                )


if __name__ == "__main__":
    unittest.main()
