"""Use the exact frozen event/page checking functions without app recovery writes."""

import ast
from datetime import datetime, timezone
import hashlib
import hmac
from pathlib import Path
import struct
from uuid import UUID

from retirement.intents import Intent, IntentConflict
from retirement.interlock import RetirementUnavailable
from retirement.pages import INITIAL, decode, page_digest


def helpers():
    source = Path(__file__).parent / "retirement/recovery.py"
    tree = ast.parse(source.read_bytes())
    names = {"event_digest", "checked_event", "checked_pages"}
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in names
        or isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id in {"DOMAIN", "EPOCH"}
            for t in node.targets
        )
    ]
    if {node.name for node in nodes if isinstance(node, ast.FunctionDef)} != names:
        raise RetirementUnavailable()
    namespace = {
        "datetime": datetime,
        "timezone": timezone,
        "hashlib": hashlib,
        "hmac": hmac,
        "struct": struct,
        "UUID": UUID,
        "Intent": Intent,
        "IntentConflict": IntentConflict,
        "RetirementUnavailable": RetirementUnavailable,
        "INITIAL": INITIAL,
        "decode": decode,
        "page_digest": page_digest,
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace
    )
    return namespace["checked_event"], namespace["checked_pages"]
