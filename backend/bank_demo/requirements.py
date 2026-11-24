"""Compare the employee's requested evidence with the report actually read."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictStr, field_validator, model_validator


class ReportRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    source: Literal["fictional_snapshot", "institution_record"]
    period_start: StrictStr | None = None
    period_end: StrictStr | None = None

    @field_validator("period_start", "period_end")
    @classmethod
    def calendar_date(cls, value):
        if value is not None and (
            len(value) != 10 or date.fromisoformat(value).isoformat() != value
        ):
            raise ValueError("bank_demo_date_invalid")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("bank_demo_date_pair_required")
        if (
            self.period_start
            and self.period_end
            and self.period_start > self.period_end
        ):
            raise ValueError("bank_demo_date_order_invalid")
        return self

    def response(self, report):
        if self.source == "institution_record":
            reason = "institution_source_unavailable"
        elif not self.period_start or not self.period_end:
            reason = "period_required"
        elif (self.period_start, self.period_end) != (
            report["periodStart"],
            report["periodEnd"],
        ):
            reason = "period_unavailable"
        else:
            return {"result": report}
        return {
            "unavailable": {
                "reason": reason,
                "reportId": report["reportId"],
                "sourceRevision": report["sourceRevision"],
                "periodStart": report["periodStart"],
                "periodEnd": report["periodEnd"],
            }
        }
