"""Explicit host locations only; production never infers QA from environment.

QA is confined to one fresh native fixture root/socket/labels. It does not
replace SQL, crypto, physical locks, normal runtime or container security.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat

BASE = Path("/srv/bank-ai/.check-results")
PRODUCTION_PRIVATE = Path("/home/ben2004/.aqua-runtime/retirement")
PREVIEW_PARENT = Path("/home/ben2004/.aqua-runtime/synthetic-preview-v2")
PREVIEW_LABEL = "restricted-preview-v2"
PREVIEW_SOCKET = "aqua-preview-app-sockets-v2"


@dataclass(frozen=True)
class Scope:
    qa_run: str | None = None
    private_preview: bool = False

    def __post_init__(self):
        if (
            type(self.private_preview) is not bool
            or self.private_preview
            and self.qa_run is not None
        ):
            raise ValueError("retirement_conflicting_deployment_scopes")
        if self.qa_run is not None and (
            type(self.qa_run) is not str
            or not re.fullmatch(r"aqua-retirement-host-[a-f0-9]{24}", self.qa_run)
        ):
            raise ValueError("retirement_QA_scope_invalid")

    @property
    def parent(self):
        if self.private_preview:
            return PREVIEW_PARENT
        return PRODUCTION_PRIVATE.parent if self.qa_run is None else BASE / self.qa_run

    @property
    def private(self):
        if self.private_preview:
            return self.parent / "retirement"
        return PRODUCTION_PRIVATE if self.qa_run is None else self.parent / "installed"

    @property
    def mail(self):
        return self.parent / "mail"

    @property
    def socket(self):
        if self.private_preview:
            return PREVIEW_SOCKET
        return "aqua_app_sockets" if self.qa_run is None else self.qa_run + "-socket"

    @property
    def plan(self):
        return self.parent / "retirement-plan.json"

    @property
    def state(self):
        return self.parent / "retirement-maintenance.json"

    @property
    def operation(self):
        return self.parent / "retirement-operation.lock"

    @property
    def install_profile(self):
        return self.parent / "retirement-install.json"

    def validate(self):
        if self.qa_run is None and not self.private_preview:
            return
        value = self.parent.lstat()
        if (
            os.geteuid() != 1000
            or self.parent.resolve(strict=True) != self.parent
            or not stat.S_ISDIR(value.st_mode)
            or value.st_uid != 1000
            or stat.S_IMODE(value.st_mode) != 0o700
        ):
            raise RuntimeError("retirement_QA_root_not_owned")

    def backend_filters(self):
        if self.private_preview:
            return [
                "--filter",
                "name=^/aqua-preview-backend-v2$",
                "--filter",
                "label=aqua.purpose=" + PREVIEW_LABEL,
            ]
        return (
            [
                "--filter",
                "label=com.docker.compose.project=bank-ai",
                "--filter",
                "label=com.docker.compose.service=backend",
            ]
            if self.qa_run is None
            else [
                "--filter",
                "label=io.aqua.run=" + self.qa_run,
                "--filter",
                "label=io.aqua.role=stopped-backend",
            ]
        )

    def holder_filters(self):
        if self.private_preview:
            return ["--filter", "label=io.aqua.deployment=" + PREVIEW_LABEL]
        return (
            []
            if self.qa_run is None
            else ["--filter", "label=io.aqua.run=" + self.qa_run]
        )

    def holder_name(self, name):
        if self.private_preview:
            return "aqua-preview-v2-" + name
        return name if self.qa_run is None else self.qa_run + "-" + name

    def child_labels(self):
        if self.private_preview:
            return ["--label=io.aqua.deployment=" + PREVIEW_LABEL]
        return ["--label=io.aqua.qa-run=" + self.qa_run] if self.qa_run else []

    def child_matches(self, labels):
        return labels.get("io.aqua.qa-run") == self.qa_run and labels.get(
            "io.aqua.deployment"
        ) == (PREVIEW_LABEL if self.private_preview else None)

    def schedule(self, run, read):
        if self.private_preview:
            current = run(["/usr/bin/crontab", "-l"])
            for line in current.splitlines():
                if not line.lstrip().startswith(b"#") and (
                    b"synthetic-preview-v2" in line or b"aqua-preview-v2-" in line
                ):
                    raise RuntimeError("retirement_preview_schedule_still_active")
            return current
        if self.qa_run is None:
            return run(["/usr/bin/crontab", "-l"])
        # This is a fresh fixture with no scheduler. Do not inspect or alter the
        # actual production crontab. The result never claims production cron.
        raw = read(self.parent / "schedule.absent")
        if raw != ("no scheduler installed for " + self.qa_run + "\n").encode():
            raise RuntimeError("retirement_QA_schedule_scope_invalid")
        return raw


PRODUCTION = Scope()
PRIVATE_PREVIEW = Scope(private_preview=True)


def selected_scope(qa_run, private_preview):
    if qa_run is None and not private_preview:
        return PRODUCTION
    if qa_run is None and private_preview is True:
        return PRIVATE_PREVIEW
    return Scope(qa_run, private_preview)
