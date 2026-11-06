"""Modeled lost-create/rename cleanup regressions; zero Docker or server actions."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / "sql-verifier"))
from verifier_process import Failure
from verifier_resources import PURPOSE, Resources

IMAGE = "sha256:" + "a" * 64
IDENT = "b" * 64


class UncertainCleanupGuards(unittest.TestCase):
    def resources(self):
        return Resources("aqua-authority-verify-" + "c" * 24, IMAGE, 90)

    def absent(self, owned):
        return (
            1,
            b"Error response from daemon: No such container: "
            + (owned.name + "-pg").encode(),
        )

    def metadata(self, owned, **labels):
        return (
            0,
            b"\n".join(
                json.dumps(value).encode()
                for value in (
                    IDENT,
                    "/" + owned.name + "-pg",
                    {
                        "io.aqua.run": owned.name,
                        "io.aqua.purpose": PURPOSE,
                        **labels,
                    },
                )
            ),
        )

    def test_lost_create_response_missing_name_stays_uncertain_and_retains_socket(self):
        owned = self.resources()
        owned.volume_attempted = True

        def lost_response(*args, **kwargs):
            self.assertEqual(owned.attempted, ["pg"])
            self.assertEqual(owned.uncertain, {"pg"})
            raise Failure("modeled_lost_create_RPC")

        with (
            patch("verifier_resources.bounded", return_value=self.absent(owned)),
            patch.object(owned, "call", side_effect=lost_response),
        ):
            with self.assertRaisesRegex(Failure, "lost_create_RPC"):
                owned.create("pg", ["postgres"])
        self.assertNotIn("pg", owned.created)
        with (
            patch("verifier_resources.bounded", return_value=self.absent(owned)),
            patch.object(owned, "call") as call,
        ):
            self.assertEqual(owned.cleanup(), [owned.name + "-pg", owned.volume])
            call.assert_not_called()
        self.assertEqual(owned.uncertain, {"pg"})

    def test_returned_ID_is_retained_before_missing_initial_verification(self):
        owned = self.resources()
        owned.volume_attempted = True
        with (
            patch("verifier_resources.bounded", return_value=self.absent(owned)),
            patch.object(owned, "call", return_value=IDENT.encode()),
        ):
            with self.assertRaisesRegex(Failure, "create_unconfirmed"):
                owned.create("pg", ["postgres"])
        self.assertEqual(owned.created, {"pg": IDENT})
        self.assertEqual(owned.uncertain, {"pg"})
        calls = []

        def renamed(*args, **kwargs):
            calls.append(args)
            self.assertEqual(args[0], "ps")
            self.assertIn("--filter=id=" + IDENT, args)
            return IDENT.encode()

        with (
            patch("verifier_resources.bounded", return_value=self.absent(owned)),
            patch.object(owned, "call", side_effect=renamed),
        ):
            self.assertEqual(owned.cleanup(), [owned.name + "-pg", owned.volume])
        self.assertEqual(len(calls), 1)
        self.assertEqual(owned.uncertain, {"pg"})

    def test_known_ID_and_name_both_absent_resolve_uncertainty(self):
        owned = self.resources()
        owned.attempted, owned.uncertain = ["pg"], {"pg"}
        owned.created["pg"] = IDENT
        with (
            patch("verifier_resources.bounded", return_value=self.absent(owned)),
            patch.object(owned, "call", return_value=b"") as call,
        ):
            self.assertEqual(owned.cleanup(), [])
        self.assertEqual(owned.uncertain, set())
        self.assertEqual(call.call_args.args[0], "ps")
        self.assertIn("--filter=id=" + IDENT, call.call_args.args)

    def test_lost_response_matching_owned_object_resolves_ID_and_is_removed(self):
        owned = self.resources()
        owned.attempted, owned.uncertain = ["pg"], {"pg"}
        owned.volume_attempted = True
        calls = []

        def call(*args, **kwargs):
            calls.append(args)
            if args[:2] == ("rm", "--force"):
                self.assertEqual(owned.created["pg"], IDENT)
                self.assertEqual(args[2], IDENT)
            if args[:2] == ("volume", "inspect"):
                return json.dumps(
                    {"io.aqua.run": owned.name, "io.aqua.purpose": PURPOSE}
                ).encode()
            return b""

        with (
            patch(
                "verifier_resources.bounded",
                side_effect=[self.metadata(owned), self.absent(owned)],
            ),
            patch.object(owned, "call", side_effect=call),
        ):
            self.assertEqual(owned.cleanup(), [])
        self.assertEqual(owned.created, {"pg": IDENT})
        self.assertEqual(owned.uncertain, set())
        self.assertIn(("rm", "--force", IDENT), calls)
        self.assertIn(("volume", "rm", owned.volume), calls)

    def test_mismatched_labels_do_not_resolve_or_remove_uncertain_object(self):
        for labels in (
            {"io.aqua.run": "foreign"},
            {"io.aqua.purpose": "foreign"},
        ):
            with self.subTest(labels=labels):
                owned = self.resources()
                owned.attempted, owned.uncertain = ["pg"], {"pg"}
                owned.volume_attempted = True
                with (
                    patch(
                        "verifier_resources.bounded",
                        return_value=self.metadata(owned, **labels),
                    ),
                    patch.object(owned, "call") as call,
                ):
                    self.assertEqual(
                        owned.cleanup(), [owned.name + "-pg", owned.volume]
                    )
                self.assertEqual(owned.created, {})
                self.assertEqual(owned.uncertain, {"pg"})
                call.assert_not_called()

    def test_malformed_create_response_never_becomes_absence(self):
        owned = self.resources()
        with (
            patch("verifier_resources.bounded", return_value=self.absent(owned)),
            patch.object(owned, "call", return_value=b"not-an-immutable-id"),
        ):
            with self.assertRaisesRegex(Failure, "create_unconfirmed"):
                owned.create("pg", ["postgres"])
        with (
            patch("verifier_resources.bounded", return_value=self.absent(owned)),
            patch.object(owned, "call") as call,
        ):
            self.assertEqual(owned.cleanup(), [owned.name + "-pg"])
            call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
