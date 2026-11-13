"""Render the exact pure production document for synthetic browser fixtures."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "auth"))
from google_redirect_bridge import document  # noqa: E402

html, headers = document(json.loads(sys.stdin.read(16384)))
print(json.dumps({"html": html, "headers": headers}))
