"""Extend the same bounded run-owned socket fixture with independent SQL only."""

import p05_browser_resources as existing
import hashlib
from p11b_browser_authority import provision


class DeletionResources(existing.Resources):
    def provision(self, image: str, report: dict) -> str:
        source = existing.source_archive()
        previous = existing.source_archive
        existing.source_archive = lambda: source
        try:
            runner = super().provision(image, report)
        finally:
            existing.source_archive = previous
        report["backend_source_sha256"] = hashlib.sha256(source).hexdigest()
        report["step"] = "app_roles"
        provision(existing.docker, self.name + "-pg", existing.ROOT)
        report["actual_independent_authority"] = True
        return runner
