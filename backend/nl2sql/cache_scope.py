"""Server-owned cache namespace; cache hits never grant authorization."""

import hashlib
import json
from dataclasses import asdict, dataclass

from nl2sql.config import Settings

POLICY_VERSION = "p01-data-boundaries-v1"


@dataclass(frozen=True)
class CacheScope:
    principal: str
    dataset: str
    authorization_revision: str
    schema_revision: str
    context_revision: str = "standalone-question-v1"
    policy_version: str = POLICY_VERSION

    def __post_init__(self) -> None:
        if any(
            not isinstance(v, str) or not v or len(v) > 512
            for v in asdict(self).values()
        ):
            raise ValueError("Cache scope requires bounded server-owned identifiers.")


def digest(value: object) -> str:
    """Structured encoding prevents separator/type collisions; never log inputs."""
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def request_scope(
    user_id: str,
    settings: Settings,
    schema_text: str,
    *,
    grant_version: int = 0,
    auth_epoch: int = 0,
) -> CacheScope:
    """Current canonical identity and durable grant revisions partition results."""
    return CacheScope(
        principal="account:" + user_id,
        dataset=digest(settings.database_url),
        authorization_revision=digest(
            [
                grant_version,
                auth_epoch,
                sorted(settings.auth_allowed_google_subs),
                sorted(settings.auth_allowed_emails),
            ]
        ),
        schema_revision=digest(schema_text),
    )
