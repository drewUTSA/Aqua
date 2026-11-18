"""Keep private saved context separate from providers and executable knowledge.

Actual session/grant/export/purge behavior requires the backend fixture tests.
These guards constrain the packaged import surface; they do not certify it.
"""

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "backend/context_notes"
MODULES = {
    "__init__.py",
    "policy.py",
    "rules.py",
    "contracts.py",
    "repository.py",
    "service.py",
    "router.py",
}
ALLOWED = {
    "__init__.py": set(),
    "policy.py": {"collections.abc", "dataclasses", "os"},
    "rules.py": {
        "datetime",
        "hashlib",
        "json",
        "unicodedata",
        "uuid",
        "context_notes.policy",
    },
    "contracts.py": {"typing", "pydantic", "context_notes", "context_notes.policy"},
    "repository.py": {
        "hashlib",
        "psycopg",
        "context_notes",
        "context_notes.policy",
        "workspace.database",
        "workspace.errors",
    },
    "service.py": {
        "collections.abc",
        "dataclasses",
        "time",
        "auth.accounts",
        "auth.security",
        "context_notes",
        "context_notes.policy",
        "privacy.retirement",
        "workspace.database",
        "workspace.errors",
        "workspace.service",
    },
    "router.py": {
        "fastapi",
        "fastapi.responses",
        "context_notes",
        "context_notes.contracts",
        "context_notes.policy",
        "context_notes.service",
        "workspace.dependencies",
        "workspace.errors",
    },
}
DYNAMIC = {
    "__import__",
    "eval",
    "exec",
    "compile",
    "globals",
    "locals",
    "vars",
    "open",
    "input",
    "breakpoint",
}
PURE_IO = {
    "open",
    "read",
    "read_bytes",
    "read_text",
    "write",
    "write_bytes",
    "write_text",
    "connect",
    "send",
    "recv",
    "execute",
    "executemany",
    "fork",
    "spawn",
    "system",
    "popen",
    "Popen",
    "unlink",
    "remove",
    "mkdir",
    "rmdir",
    "replace",
    "rename",
}


class ContextNotesPackaging(unittest.TestCase):
    def test_exact_sdk_free_package_and_closed_import_surface(self):
        self.assertEqual({p.name for p in PACKAGE.glob("*.py")}, MODULES)
        for name in MODULES:
            tree = ast.parse((PACKAGE / name).read_bytes(), filename=name)
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(item.name for item in node.names)
                elif isinstance(node, ast.ImportFrom):
                    self.assertEqual(node.level, 0)
                    imports.add(node.module)
                    self.assertNotIn("*", {item.name for item in node.names})
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, DYNAMIC)
            self.assertLessEqual(imports, ALLOWED[name], name)

    def test_rules_cannot_load_store_or_execute_context(self):
        tree = ast.parse((PACKAGE / "rules.py").read_bytes())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, PURE_IO)

    def test_image_copies_only_named_runtime_python(self):
        docker = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
        ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertEqual(
            [line for line in docker.splitlines() if "context_notes" in line],
            ["COPY --chown=1000:1000 backend/context_notes/*.py ./context_notes/"],
        )
        self.assertEqual(
            [line for line in ignore.splitlines() if "context_notes" in line],
            ["!backend/context_notes/*.py"],
        )
        self.assertEqual({p.suffix for p in PACKAGE.iterdir() if p.is_file()}, {".py"})


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("notes_boundary_requires_assertions")
    unittest.main()
