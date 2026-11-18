"""Source boundaries for the provider-free saved-result read increment.

These do not replace real-session, precision, native-image or browser checks.
"""

import ast
import fnmatch
from pathlib import Path
import shlex
import unittest

ROOT = Path(__file__).resolve().parents[2]
if not __debug__:
    raise RuntimeError("source_boundary_guards_require_assertions")
PACKAGE = ROOT / "backend/result_companion"
MODULES = {"__init__.py", "facts.py", "service.py", "router.py"}
PURE_IMPORTS = {"collections.abc", "datetime", "decimal", "json", "math", "re"}
DOORWAY_IMPORTS = {
    "service.py": {
        "collections.abc.Callable",
        "time",
        "analysis.records",
        "auth.security.UserSession",
        "companion.policy.CompanionPolicy",
        "result_companion.facts.build",
        "result_companion.facts.encoded",
        "result_companion.facts.require",
        "workspace.errors.WorkspaceError",
        "workspace.service.Workspace",
    },
    "router.py": {
        "fastapi.APIRouter",
        "fastapi.Request",
        "pydantic.BaseModel",
        "pydantic.ConfigDict",
        "pydantic.Field",
        "pydantic.StrictInt",
        "pydantic.StrictStr",
        "pydantic.field_validator",
        "companion.policy.CompanionPolicy",
        "result_companion.service.ResultCompanion",
        "workspace.dependencies.Service",
        "workspace.dependencies.Session",
        "workspace.dependencies.perform",
        "workspace.errors.WorkspaceError",
    },
}
DYNAMIC = {
    "__builtins__",
    "__import__",
    "breakpoint",
    "compile",
    "delattr",
    "eval",
    "exec",
    "globals",
    "input",
    "locals",
    "open",
    "setattr",
    "vars",
}
IO_METHODS = {
    "apply",
    "chmod",
    "chown",
    "connect",
    "delete",
    "encrypt",
    "dump",
    "execute",
    "executemany",
    "fork",
    "hardlink_to",
    "mkdir",
    "load",
    "open",
    "popen",
    "Popen",
    "query",
    "read",
    "read_bytes",
    "read_text",
    "recv",
    "rename",
    "rmdir",
    "run",
    "send",
    "spawn",
    "submit",
    "symlink_to",
    "system",
    "unlink",
    "write",
    "write_bytes",
    "write_text",
}


def tree(name):
    return ast.parse((PACKAGE / name).read_bytes(), filename=name)


def imported(value):
    """Resolve aliases without importing application/dependency code."""
    result = {}
    for node in ast.walk(value):
        if isinstance(node, ast.Import):
            for entry in node.names:
                result[entry.asname or entry.name.split(".")[0]] = entry.name
        elif isinstance(node, ast.ImportFrom):
            assert (
                not node.level
                and node.module
                and all(entry.name != "*" for entry in node.names)
            )
            for entry in node.names:
                result[entry.asname or entry.name] = node.module + "." + entry.name
    return result


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted(node.value) + "." + node.attr
    return ""


def qualified(node, aliases):
    name = dotted(node)
    first, _, rest = name.partition(".")
    return aliases.get(first, first) + ("." + rest if rest else "")


def common_boundary(value, *, pure=False, aliases=None):
    for node in ast.walk(value):
        if isinstance(node, ast.Name):
            assert node.id not in DYNAMIC
            if pure:
                assert node.id != "getattr"
        if isinstance(node, ast.Attribute):
            assert not node.attr.startswith("__")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            fixed_result_read = (
                aliases is not None
                and node.func.attr == "read"
                and isinstance(node.func.value, ast.Call)
                and qualified(node.func.value.func, aliases)
                == "result_companion.service.ResultCompanion"
            )
            assert node.func.attr not in IO_METHODS or fixed_result_read


def pure_boundary(value):
    aliases = imported(value)
    assert all(
        name in PURE_IMPORTS or name.rpartition(".")[0] in PURE_IMPORTS
        for name in aliases.values()
    )
    common_boundary(value, pure=True)


def doorway_boundary(name, value):
    aliases = imported(value)
    assert set(aliases.values()) <= DOORWAY_IMPORTS[name]
    common_boundary(value, aliases=aliases)
    reads = set()
    for node in ast.walk(value):
        if isinstance(node, ast.Attribute):
            reference = qualified(node, aliases)
            if reference.startswith("analysis.records."):
                assert reference in {
                    "analysis.records.get",
                    "analysis.records.authorize",
                    "analysis.records.snapshot",
                }
                reads.add(reference)
        if not isinstance(node, ast.Call):
            continue
        target = dotted(node.func)
        if target.startswith("self.workspace."):
            assert target in {
                "self.workspace.reserve",
                "self.workspace.storage.transaction",
            }
        assert not target.startswith(("conn.", "request.app."))
        if target == "getattr":
            assert name == "router.py" and len(node.args) == 3 and not node.keywords
            assert dotted(node.args[0]) == "request.app.state"
            assert (
                isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "companion_policy"
            )
            assert (
                isinstance(node.args[2], ast.Call)
                and qualified(node.args[2].func, aliases)
                == "companion.policy.CompanionPolicy"
            )
        if isinstance(node.func, ast.Attribute) and node.func.attr == "post":
            assert target == "router.post" and len(node.args) == 1
            assert (
                isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "/result-brief"
            )
    if name == "service.py":
        assert reads == {
            "analysis.records.get",
            "analysis.records.authorize",
            "analysis.records.snapshot",
        }


class ResultCompanionPackaging(unittest.TestCase):
    def test_runtime_namespace_is_exactly_four_modules_and_one_explicit_copy_rule(self):
        files = list(PACKAGE.rglob("*.py"))
        self.assertEqual(
            {path.relative_to(PACKAGE).as_posix() for path in files}, MODULES
        )
        self.assertTrue(
            all(
                not path.is_symlink() and path.stat().st_size <= 65536 for path in files
            )
        )
        self.assertFalse(
            any(
                isinstance(node, (ast.Import, ast.ImportFrom, ast.Call))
                for node in ast.walk(tree("__init__.py"))
            )
        )
        rules = [
            line.strip()
            for line in (ROOT / ".dockerignore").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(rules[0], "**")
        admitted = [rule[1:] for rule in rules[1:] if rule.startswith("!")]
        for name in MODULES:
            target = "backend/result_companion/" + name
            self.assertEqual(
                [
                    pattern
                    for pattern in admitted
                    if fnmatch.fnmatchcase(target, pattern)
                    or pattern.rstrip("/") in {"backend", "backend/result_companion"}
                ],
                ["backend/result_companion/*.py"],
            )
        self.assertEqual(
            [rule for rule in admitted if rule.startswith("backend/result_companion")],
            ["backend/result_companion/*.py"],
        )
        copies = []
        for line in (ROOT / "backend/Dockerfile").read_text().splitlines():
            if line.startswith("COPY "):
                parts = shlex.split(line)
                for source in (p for p in parts[1:-1] if not p.startswith("--")):
                    if source.rstrip("/") in {
                        ".",
                        "backend",
                        "backend/result_companion",
                    } or fnmatch.fnmatchcase(
                        "backend/result_companion/facts.py", source
                    ):
                        copies.append((source, parts[-1]))
        self.assertEqual(
            copies, [("backend/result_companion/*.py", "./result_companion/")]
        )

    def test_facts_are_closed_stdlib_without_files_network_or_dynamic_code(self):
        pure_boundary(tree("facts.py"))

    def test_service_and_router_admit_only_fixed_authorized_read_dependencies(self):
        for name in ("service.py", "router.py"):
            with self.subTest(module=name):
                doorway_boundary(name, tree(name))

    def test_guards_reject_provider_io_dynamic_and_persistence_additions(self):
        for attack in (
            "import socket",
            "from pathlib import Path\nPath('/private').read_text()",
            "import json\njson.load(source_file)",
            "x=__import__('os')",
            "x=().__class__",
        ):
            with self.subTest(attack=attack), self.assertRaises(AssertionError):
                pure_boundary(ast.parse(attack))
        for attack in (
            "from analysis import service",
            "records.insert(None)",
            "self.workspace.apply(None)",
            "conn.execute('SELECT 1')",
            "request.app.state.workspace_query('input')",
        ):
            value = tree("service.py")
            value.body.extend(ast.parse(attack).body)
            with self.subTest(attack=attack), self.assertRaises(AssertionError):
                doorway_boundary("service.py", value)


if __name__ == "__main__":
    unittest.main()
