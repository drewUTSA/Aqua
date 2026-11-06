"""Current executable fixtures cannot reuse an older or ambiguous schema."""

from unittest.mock import patch

import pytest

import p05_browser_host as host
import p05_browser_worker as worker

MODES = (
    {},
    {"account_security_fixture": True},
    {"account_security_fixture": True, "account_identity_fixture": True},
    {
        "account_security_fixture": True,
        "account_identity_fixture": True,
        "personal_export_fixture": True,
    },
    {
        "account_security_fixture": True,
        "account_identity_fixture": True,
        "personal_deletion_fixture": True,
    },
)


@pytest.mark.parametrize("module", (host, worker))
@pytest.mark.parametrize("schema", (6, 7, 8, 10, True, 9.0, "9"))
@pytest.mark.parametrize("flags", MODES)
def test_every_candidate_mode_rejects_non_schema9_before_resources_or_app_import(
    module, schema, flags
):
    with (
        patch.object(module, "fixture_schema", return_value=schema),
        patch.object(host, "Resources") as resources,
        patch.object(worker, "guard_fixture") as runtime,
        pytest.raises(ValueError, match="fixture_schema9_required"),
    ):
        if module is host:
            host.host(
                "https://aqua-browser.example.test", "sha256:" + "a" * 64, True, **flags
            )
        else:
            worker.worker("https://aqua-browser.example.test", True, **flags)
    resources.assert_not_called()
    runtime.assert_not_called()
