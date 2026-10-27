"""Closed bridge route/method/query bounds retain actual API rejection tests."""

import unittest

from p06_browser_routes import workspace_route

ID = "c5fbc248-64cb-4f08-b2be-e38df9d7b331"


class Routes(unittest.TestCase):
    def test_owned_workspace_methods_and_queries_are_forwardable(self) -> None:
        for path, method in [
            ("/api/v1/chats", "GET"),
            ("/api/v1/chats/search", "POST"),
            (f"/api/v1/chats/{ID}/messages?limit=20&cursor=forged", "GET"),
            (f"/api/v1/chats/{ID}?revision=1", "DELETE"),
            (f"/api/v1/projects/{ID}", "PATCH"),
            (f"/api/v1/me/saved-prompts/{ID}/uses", "POST"),
            ("/api/v1/me/saved-prompts?cursor=foreign-owner-cursor", "GET"),
        ]:
            with self.subTest(path=path, method=method):
                self.assertTrue(workspace_route(path, method))

    def test_paths_methods_private_search_queries_and_unknown_parameters_are_denied(
        self,
    ) -> None:
        for path, method in [
            ("https://evil.invalid/api/v1/chats", "GET"),
            ("/api/v1/chats/search?search=PRIVATE", "POST"),
            ("/api/v1/chats?search=PRIVATE", "GET"),
            ("/api/v1/chats/not-a-uuid", "PATCH"),
            (f"/api/v1/chats/{ID}", "PUT"),
            ("/api/v1/admin", "GET"),
            ("/api/v1/projects?owner_id=forged", "GET"),
            ("/api/v1/chats?limit=1&limit=2", "GET"),
            ("/api/v1/chats?cursor=" + "x" * 1025, "GET"),
        ]:
            with self.subTest(method=method):
                self.assertFalse(workspace_route(path, method))

    def test_analysis_monitoring_and_cancel_have_no_mutable_query_authority(
        self,
    ) -> None:
        prefix = f"/api/v1/analysis-requests/{ID}"
        for path, method in [
            (prefix, "GET"),
            (prefix + "/events", "GET"),
            (prefix + "/cancel", "POST"),
        ]:
            self.assertTrue(workspace_route(path, method))
        for path, method in [
            (prefix, "POST"),
            (prefix + "/cancel", "GET"),
            (prefix + "/events?owner=foreign", "GET"),
            (prefix + "?model=gemini", "GET"),
        ]:
            self.assertFalse(workspace_route(path, method))


if __name__ == "__main__":
    unittest.main()
