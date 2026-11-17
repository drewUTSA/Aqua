"""Exact SDK-free fictional report inputs shared by isolated check archives."""

import io
from pathlib import Path
import tarfile

CORE_SOURCES = (
    "eval/__init__.py",
    "eval/banking/__init__.py",
    "eval/banking/catalog.py",
    "eval/banking/data.py",
    "eval/banking/knowledge.py",
    "eval/banking/proposals.py",
    "eval/banking/reports.py",
    "eval/banking/scope.py",
    "mcp_demo/__init__.py",
    "mcp_demo/data.py",
    "mcp_demo/guidance.py",
    "mcp_demo/protocol.py",
    "mcp_demo/reports.py",
    "mcp_demo/web.py",
    "mcp_demo/fixtures/bank.json",
)


def add_sources(archive: tarfile.TarFile, root: Path) -> None:
    """Never expand the stdio server, SDK, evaluation runners or training data."""
    admitted = set(archive.getnames())
    total = 0
    for name in CORE_SOURCES:
        path = root / name
        if (
            path.is_symlink()
            or path.resolve(strict=True) != path.absolute()
            or not path.is_file()
        ):
            raise RuntimeError("bank_demo_check_source_path")
        size = path.stat().st_size
        if not 0 <= size <= 131072:
            raise RuntimeError("bank_demo_check_source_capacity")
        raw = path.read_bytes()
        total += len(raw)
        if len(raw) != size or total > 1024 * 1024:
            raise RuntimeError("bank_demo_check_source_changed_or_capacity")
        if name in admitted:
            continue
        item = tarfile.TarInfo(name)
        item.size, item.mode, item.uid, item.gid = len(raw), 0o644, 1000, 1000
        archive.addfile(item, io.BytesIO(raw))
        admitted.add(name)
