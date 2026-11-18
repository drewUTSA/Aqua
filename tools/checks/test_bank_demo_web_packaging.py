"""Source-only guards for the exact SDK-free fictional-report runtime closure.

These checks qualify package selection and pure imports, not authentication,
native image contents, model quality or a deployed bank integration.
"""

import ast
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MCP_FILES = frozenset(
    f"mcp_demo/{name}.py"
    for name in ("__init__", "data", "protocol", "reports", "guidance", "web")
)
BANK_FILES = frozenset(
    f"eval/banking/{name}.py"
    for name in (
        "__init__",
        "catalog",
        "data",
        "knowledge",
        "proposals",
        "reports",
        "scope",
    )
)
FIXTURE = "mcp_demo/fixtures/bank.json"
CORE_FILES = MCP_FILES | BANK_FILES | {"eval/__init__.py", FIXTURE}
SOURCE_REVISION = "8c27aa965ae4087fc965f66957ab08dde9b18de1cf6abdd321102afb6f8cdd37"
COMPANION_GUARD_SHA256 = (
    "98d550c5b9ec2bf1ef4a773414063b6788b6bb06b9f730fb8db72a4f460ec9bf"
)
PURE_STDLIB = {
    "collections",
    "dataclasses",
    "datetime",
    "decimal",
    "hashlib",
    "json",
    "pathlib",
    "re",
    "time",
    "types",
    "unicodedata",
    "uuid",
}
FORBIDDEN_NAMES = {
    "__builtins__",
    "__import__",
    "breakpoint",
    "compile",
    "delattr",
    "eval",
    "exec",
    "getattr",
    "globals",
    "input",
    "locals",
    "open",
    "print",
    "setattr",
}
FORBIDDEN_METHODS = {
    "chmod",
    "chown",
    "connect",
    "hardlink_to",
    "mkdir",
    "read_bytes",
    "read_text",
    "rename",
    "rmdir",
    "symlink_to",
    "unlink",
    "write",
    "write_bytes",
    "write_text",
}


def module_name(path):
    name = path.removesuffix(".py").replace("/", ".")
    return name.removesuffix(".__init__")


def imports(tree, module, package):
    """Resolve ordinary and relative imports without importing the source."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (entry.name for entry in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = node.module or ""
            if node.level:
                parts = package.split(".")
                if node.level > len(parts):
                    raise AssertionError(f"relative import leaves closure: {module}")
                name = ".".join(parts[: len(parts) - node.level + 1] + [name])
            yield name
            if name in {"mcp_demo", "eval"}:
                yield from (f"{name}.{entry.name}" for entry in node.names)
            if any(entry.name == "*" for entry in node.names):
                raise AssertionError(f"wildcard import in closure: {module}")


def core_copies():
    """Interpret only the reviewed plain COPY form; unknown forms fail closed."""
    result = []
    for line in (ROOT / "backend/Dockerfile").read_text(encoding="utf-8").splitlines():
        if not line.startswith("COPY "):
            continue
        parts = shlex.split(line)
        sources = [part for part in parts[1:-1] if not part.startswith("--")]
        for source in sources:
            if source == "eval" or source.startswith(("eval/", "mcp_demo")):
                target = parts[-1].removeprefix("./")
                if target.endswith("/"):
                    target += source.rsplit("/", 1)[-1]
                result.append((source, target))
    return result


def run_staged_core(script):
    """Run only the admitted public source in a bounded, site-package-free child."""
    with tempfile.TemporaryDirectory(prefix="aqua-bank-core-") as folder:
        for relative in CORE_FILES:
            target = Path(folder) / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        environment = {
            key: os.environ[key]
            for key in ("SYSTEMROOT", "WINDIR")
            if key in os.environ
        }
        return subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", script],
            cwd=folder,
            env=environment,
            capture_output=True,
            timeout=8,
            check=False,
        )


class BankDemoWebPackaging(unittest.TestCase):
    def test_build_context_admits_only_the_exact_pure_core_and_one_fixture(self):
        lines = [
            line.strip()
            for line in (ROOT / ".dockerignore")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(lines[0], "**")
        allowed = [
            line[1:] for line in lines[1:] if line.startswith(("!eval", "!mcp_demo"))
        ]
        self.assertCountEqual(allowed, CORE_FILES)
        self.assertTrue(all("*" not in item and "?" not in item for item in allowed))

    def test_docker_copies_exactly_that_closure_to_matching_package_paths(self):
        copies = core_copies()
        self.assertCountEqual([source for source, _ in copies], CORE_FILES)
        self.assertTrue(all(source == target for source, target in copies))

    def test_transitive_core_imports_are_closed_stdlib_only_and_have_no_tool_io(self):
        modules = {module_name(path) for path in CORE_FILES if path.endswith(".py")}
        total = 0
        for relative in sorted(CORE_FILES - {FIXTURE}):
            path = ROOT / relative
            self.assertFalse(path.is_symlink(), relative)
            raw = path.read_bytes()
            total += len(raw)
            self.assertLessEqual(len(raw), 65536, relative)
            tree = ast.parse(raw, filename=relative)
            module = module_name(relative)
            package = (
                module if path.name == "__init__.py" else module.rpartition(".")[0]
            )
            with self.subTest(module=module):
                self.assertLessEqual(
                    set(imports(tree, module, package)), modules | PURE_STDLIB
                )
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name):
                        self.assertNotIn(node.id, FORBIDDEN_NAMES)
                    if isinstance(node, ast.Call) and isinstance(
                        node.func, ast.Attribute
                    ):
                        self.assertNotIn(node.func.attr, FORBIDDEN_METHODS)
                        if node.func.attr in {"open", "read"}:
                            self.assertEqual(relative, "mcp_demo/data.py")
        self.assertLessEqual(total, 256 * 1024)
        self.assertEqual((ROOT / "eval/__init__.py").read_bytes(), b"")

    def test_only_fixture_read_uses_a_fixed_path_and_existing_bounded_loader(self):
        tree = ast.parse((ROOT / "mcp_demo/data.py").read_text(encoding="utf-8"))
        loader = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_load_fixture"
        )
        path = next(
            node.value
            for node in loader.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(item, ast.Name) and item.id == "path"
                for item in node.targets
            )
        )
        expected = ast.parse(
            'Path(__file__).resolve().parent / "fixtures" / "bank.json"', mode="eval"
        ).body
        self.assertEqual(ast.dump(path), ast.dump(expected))
        io_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"open", "read"}
        ]
        self.assertCountEqual(
            [ast.unparse(node) for node in io_calls],
            ["path.open('rb')", "source.read(32769)"],
        )

    def test_approved_fixture_is_small_synthetic_and_preserves_canonical_revision(self):
        path = ROOT / FIXTURE
        self.assertFalse(path.is_symlink())
        raw = path.read_bytes()
        self.assertLessEqual(len(raw), 32768)
        value = json.loads(raw.decode("utf-8"))
        canonical = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), SOURCE_REVISION)
        self.assertIs(value["synthetic"], True)
        self.assertEqual(value["as_of"], "2026-11-16")
        self.assertEqual(value["currency"], "USD")

    def test_selected_files_import_without_site_packages_or_unselected_modules(self):
        script = """
import importlib
import importlib.util
import sys
sys.path.insert(0, '.')
for name in ('eval.banking', 'mcp_demo.data', 'mcp_demo.protocol',
             'mcp_demo.reports', 'mcp_demo.guidance', 'mcp_demo.web'):
    importlib.import_module(name)
from mcp_demo.data import SOURCE_REVISION
assert SOURCE_REVISION == '8c27aa965ae4087fc965f66957ab08dde9b18de1cf6abdd321102afb6f8cdd37'
for name in ('mcp', 'mcp_types', 'mcp_demo.server', 'mcp_demo.__main__',
             'mcp_demo.finance', 'mcp_demo.finance_schema', 'mcp_demo.trends',
             'eval.run_eval', 'eval.monthly_trend', 'eval.datasets'):
    assert importlib.util.find_spec(name) is None, 'unexpected package in closure'
assert not any(name == 'mcp' or name.startswith('mcp.') for name in sys.modules)
print('bank_demo_pure_closure_ok')
"""
        result = run_staged_core(script)
        self.assertEqual(result.returncode, 0, "pure closure import failed")
        self.assertEqual(
            result.stdout.replace(b"\r\n", b"\n"), b"bank_demo_pure_closure_ok\n"
        )
        self.assertEqual(result.stderr, b"")

    def test_staged_web_contract_preserves_all_core_rows_and_closed_demo_scope(self):
        script = """
import json
import sys
sys.path.insert(0, '.')
from mcp_demo import reports, web
from eval.banking.data import BankingDenied
from mcp_demo.protocol import actor_for

expected_scopes = {
    'none': set(),
    'teller': {'deposit_portfolio_summary', 'service_case_summary'},
    'analyst': {'reconciliation_summary', 'liquidity_assumption_summary',
                'credit_review_summary', 'commercial_exposure_summary'},
}
for persona, expected in expected_scopes.items():
    assert {row['id'] for row in web.context(actor_for(persona))['reports']} == expected
manager = actor_for('manager')
assert len(web.context(manager)['reports']) == 17
fields = set('''asOf sourceRevision guidanceRevision synthetic demoOnly jurisdiction
currency executionEnabled approvalRecorded reportId title department period
periodStart periodEnd periodComplete truncated readOnly definition columns rows
rowCount caveats procedure nextSteps'''.split())
for report_id in web.REPORT_IDS:
    original = reports.run_report(manager, report_id)
    projected = web.report(manager, report_id)
    assert set(projected) == fields
    assert [column['key'] for column in projected['columns']] == list(original['rows'][0])
    assert projected['rows'] == [[str(cell) for cell in row.values()] for row in original['rows']]
    assert projected['definition'] == original['metric_definition']
    assert projected['rowCount'] == len(projected['rows']) <= 12
    assert len(projected['caveats']) == len(projected['nextSteps']) == 3
    assert set(projected['procedure']) == {'title','text','sourceId','version','contentSha256','fictional'}
    assert projected['procedure']['fictional'] is True
    assert projected['synthetic'] is projected['demoOnly'] is projected['readOnly'] is True
    assert projected['executionEnabled'] is projected['approvalRecorded'] is projected['periodComplete'] is False
    outer = {'schemaVersion': 1, 'owner_id': '33333333-3333-4333-8333-333333333333', 'result': projected}
    assert len(json.dumps(outer, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) <= 32768
deposit = web.report(manager, 'deposit_portfolio_summary')
assert deposit['rows'][0] == ['north', 'checking', '1200', '1461250.00']
assert [column['unit'] for column in deposit['columns']] == ['text','text','count','USD']
try:
    web.report(actor_for('teller'), 'reconciliation_summary')
except BankingDenied as error:
    assert str(error) == 'report_scope_denied'
else:
    raise AssertionError('demo scope broadened')
print('bank_demo_web_contract_ok')
"""
        result = run_staged_core(script)
        self.assertEqual(result.returncode, 0, "staged web contract failed")
        self.assertEqual(
            result.stdout.replace(b"\r\n", b"\n"), b"bank_demo_web_contract_ok\n"
        )
        self.assertEqual(result.stderr, b"")

    def test_original_ten_module_companion_packaging_guard_is_unchanged(self):
        text = (ROOT / "tools/checks/test_companion_packaging.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            hashlib.sha256(text.encode("utf-8")).hexdigest(), COMPANION_GUARD_SHA256
        )


if __name__ == "__main__":
    unittest.main()
