"""One server policy bounds jobs across sessions, processes and route aliases."""

LOCK = 1095848263
DEADLINE_SECONDS = 120
LEASE_SECONDS = 15
KILL_GRACE_SECONDS = 15
RUNNING_GLOBAL = 2
RUNNING_OWNER = 1
QUEUED_GLOBAL = 8
QUEUED_OWNER = 2
TERMINAL = frozenset({"complete", "error", "cancelled", "interrupted", "expired"})
STAGES = (
    frozenset(
        {
            "queued",
            "context",
            "schema",
            "retrieval",
            "generating",
            "validating",
            "executing",
            "summarizing",
            "persisting",
            "cancelling",
        }
    )
    | TERMINAL
)
MAX_CONTEXT_BYTES = 12288
MAX_EVENTS = 32
MAX_RESULT_BYTES = 240000
MAX_FRAME_BYTES = 262144
