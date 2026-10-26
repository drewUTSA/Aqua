"""Closed fixture controls never accept arbitrary owners or dataset targets."""

import unittest
from unittest.mock import MagicMock, Mock

from p05_browser_messages import dispatch
from p06_browser_analysis import AnalysisFixture, FIXTURE_EMAIL


class AnalysisControls(unittest.TestCase):
    def test_default_fixture_refuses_all_analysis_controls_without_work(self) -> None:
        storage = Mock()
        for kind in ("workspace_grant", "workspace_revoke", "workspace_stats"):
            with self.assertRaisesRegex(ValueError, "not_enabled"):
                dispatch(
                    {"id": "fixture", "kind": kind}, None, storage, lambda: False, []
                )
        storage.transaction.assert_not_called()

    def test_control_payload_cannot_select_an_owner_or_connection(self) -> None:
        fixture = AnalysisFixture.__new__(AnalysisFixture)
        fixture.storage = Mock()
        for extra in (
            {"owner_id": "foreign"},
            {"email": "other@example.test"},
            {"dataset": "hosted"},
            {"enabled": True},
        ):
            with self.assertRaisesRegex(ValueError, "control_invalid"):
                fixture.control({"id": "fixture", "kind": "workspace_grant", **extra})
        fixture.storage.transaction.assert_not_called()

    def test_grant_and_revoke_are_single_use_and_bind_exact_fixed_account(self) -> None:
        fixture = AnalysisFixture.__new__(AnalysisFixture)
        fixture.storage, fixture.owner, fixture.retired = MagicMock(), None, False
        fixture.dataset, fixture.executions = "a" * 64, 0
        connection = fixture.storage.transaction.return_value.__enter__.return_value
        connection.execute.return_value.fetchone.return_value = (
            "00000000-0000-4000-8000-000000000001",
        )
        self.assertTrue(
            fixture.control({"id": "grant", "kind": "workspace_grant"})["enabled"]
        )
        self.assertEqual(connection.execute.call_args_list[0].args[1], (FIXTURE_EMAIL,))
        with self.assertRaisesRegex(ValueError, "grant_replay"):
            fixture.control({"id": "grant-again", "kind": "workspace_grant"})
        self.assertFalse(
            fixture.control({"id": "revoke", "kind": "workspace_revoke"})["enabled"]
        )
        with self.assertRaisesRegex(ValueError, "revoke_invalid"):
            fixture.control({"id": "revoke-again", "kind": "workspace_revoke"})
        with self.assertRaisesRegex(ValueError, "grant_replay"):
            fixture.control({"id": "grant-after-revoke", "kind": "workspace_grant"})
        stats = fixture.control({"id": "stats", "kind": "workspace_stats"})
        self.assertEqual(
            (stats["fake_executions"], stats["actual_provider_calls"]), (0, 0)
        )


if __name__ == "__main__":
    unittest.main()
