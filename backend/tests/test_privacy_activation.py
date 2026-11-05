"""Explicit single-process activation; no environment value proves topology."""

import unittest

from privacy.policy import ACTIVATION_FLAG, activation, pool_budget, runtime_context

ARGV = ["/usr/local/bin/uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]


class ActivationTests(unittest.TestCase):
    def test_default_is_closed_and_only_the_exact_bool_activates(self):
        self.assertFalse(activation({}, ARGV))
        for value in ("false", "TRUE", "1", "yes", "", " true", "true "):
            with self.subTest(value=value):
                self.assertFalse(activation({ACTIVATION_FLAG: value}, ARGV))
        self.assertTrue(activation({ACTIVATION_FLAG: "true"}, ARGV))

    def test_only_reviewed_n1_p4_mail1_pool_inventory_is_supported(self):
        self.assertEqual(pool_budget(1, 4), 8)
        for values in ((2, 1), (2, 4), (1, 1), (1, 5), (True, 4), (1, True), (1, 4, 2)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                pool_budget(*values)

    def test_worker_cli_parent_manager_and_noncanonical_env_are_closed(self):
        for argv in (
            ARGV + ["--workers", "2"],
            ARGV + ["--workers", "1"],
            ARGV + ["--reload"],
            ["gunicorn", "main:app"],
            ["python", "-m", "uvicorn", *ARGV[1:]],
            [],
        ):
            with self.subTest(argv=argv):
                self.assertFalse(activation({ACTIVATION_FLAG: "true"}, argv))
        self.assertFalse(runtime_context(ARGV, child=True))
        for key, value in (
            ("WEB_CONCURRENCY", "2"),
            ("UVICORN_WORKERS", "2"),
            ("WEB_CONCURRENCY", "01"),
            ("UVICORN_RELOAD", "true"),
            ("SERVER_SOFTWARE", "gunicorn"),
            ("GUNICORN_CMD_ARGS", "--workers 2"),
        ):
            with self.subTest(key=key):
                self.assertFalse(
                    activation({ACTIVATION_FLAG: "true", key: value}, ARGV)
                )


if __name__ == "__main__":
    unittest.main()
