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


@dataclass(frozen=True)
class Scope:
    qa_run: str | None = None

    def __post_init__(self):
        if self.qa_run is not None and (
            type(self.qa_run) is not str
            or not re.fullmatch(r"aqua-retirement-host-[a-f0-9]{24}", self.qa_run)
        ):
            raise ValueError("retirement_QA_scope_invalid")

    @property
    def parent(self):
        return PRODUCTION_PRIVATE.parent if self.qa_run is None else BASE / self.qa_run

    @property
    def private(self):
        return PRODUCTION_PRIVATE if self.qa_run is None else self.parent / "installed"

    @property
    def mail(self):
        return self.parent / "mail"

    @property
    def socket(self):
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
        if self.qa_run is None:
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
        return (
            []
            if self.qa_run is None
            else ["--filter", "label=io.aqua.run=" + self.qa_run]
        )

    def holder_name(self, name):
        return name if self.qa_run is None else self.qa_run + "-" + name

    def schedule(self, run, read):
        if self.qa_run is None:
            return run(["/usr/bin/crontab", "-l"])
        # This is a fresh fixture with no scheduler. Do not inspect or alter the
        # actual production crontab. The result never claims production cron.
        raw = read(self.parent / "schedule.absent")
        if raw != ("no scheduler installed for " + self.qa_run + "\n").encode():
            raise RuntimeError("retirement_QA_schedule_scope_invalid")
        return raw


PRODUCTION = Scope()
