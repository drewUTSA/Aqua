"""Strict P10b DTO checks run offline as well as in the canonical matrix."""

import unittest

from pydantic import ValidationError

from account.action_contracts import (
    ActionProof,
    ActionTarget,
    PasswordChange,
    PasswordReauth,
)

ID = "00000000-0000-4000-8000-000000000001"
TOKEN = "v2." + "x" * 43


class ActionContractTests(unittest.TestCase):
    def test_only_three_implemented_operations_are_accepted(self):
        for operation in ["password_change", "sessions_revoke_all"]:
            self.assertEqual(
                ActionTarget.model_validate({"operation": operation}).operation,
                operation,
            )
        for operation in [
            "password_add",
            "google_link",
            "google_unlink",
            "email_change",
            "mfa",
            True,
            1,
            None,
        ]:
            with self.subTest(operation=operation), self.assertRaises(ValidationError):
                ActionTarget.model_validate({"operation": operation})

    def test_session_target_is_exact_and_only_accepted_for_one_revoke(self):
        self.assertEqual(
            ActionTarget.model_validate(
                {"operation": "session_revoke", "target_session_id": ID}
            ).target_session_id,
            ID,
        )
        for body in [
            {"operation": "session_revoke"},
            {"operation": "session_revoke", "target_session_id": "bad"},
            {"operation": "password_change", "target_session_id": ID},
            {"operation": "sessions_revoke_all", "target_session_id": ID},
        ]:
            with self.assertRaises(ValidationError):
                ActionTarget.model_validate(body)

    def test_server_authority_and_verified_claims_cannot_be_mass_assigned(self):
        for key in [
            "owner_id",
            "user_id",
            "method",
            "verified",
            "auth_epoch",
            "target_digest",
            "expires_at",
            "__proto__",
        ]:
            with self.subTest(key=key), self.assertRaises(ValidationError):
                ActionTarget.model_validate(
                    {"operation": "password_change", key: "forged"}
                )

    def test_opaque_tokens_are_strict_and_do_not_accept_prior_email_proofs(self):
        self.assertEqual(
            ActionProof.model_validate({"proof_token": TOKEN}).proof_token, TOKEN
        )
        for value in [
            TOKEN[3:],
            "v1." + "x" * 43,
            "v2." + "x" * 42,
            TOKEN + "\n",
            4,
            True,
            {},
            None,
        ]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ActionProof.model_validate({"proof_token": value})

    def test_credentials_are_bounded_strict_and_excluded_from_representations(self):
        body = PasswordReauth(
            operation="password_change",
            challenge_id=ID,
            challenge_token=TOKEN,
            password="private-current-password",
        )
        self.assertNotIn("private-current-password", repr(body))
        self.assertNotIn(TOKEN, repr(body))
        changed = PasswordChange(proof_token=TOKEN, new_password="private-new-password")
        self.assertNotIn("private-new-password", repr(changed))
        self.assertNotIn(TOKEN, repr(changed))
        for value in [True, 123, "", "x" * 513]:
            with self.assertRaises(ValidationError):
                PasswordChange.model_validate(
                    {"proof_token": TOKEN, "new_password": value}
                )


if __name__ == "__main__":
    unittest.main()
