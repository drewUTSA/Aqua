"""Offline DTO regressions for method ownership and distinct bearer audiences."""

import unittest
from pydantic import ValidationError
from account.identity_contracts import (
    EmailCompletion,
    GoogleChallenge,
    GoogleVerification,
    IdentityTarget,
    NotificationUpdate,
    PasswordEnrollment,
)

ID = "00000000-0000-4000-8000-000000000001"
TOKEN = "v2." + "x" * 43


class IdentityContractTests(unittest.TestCase):
    def test_target_fields_are_operation_specific(self):
        self.assertEqual(
            IdentityTarget.model_validate(
                {"operation": "email_change", "new_email": "New+tag@EXAMPLE.invalid"}
            ).new_email,
            "new+tag@example.invalid",
        )
        self.assertEqual(
            IdentityTarget.model_validate(
                {"operation": "google_unlink", "target_identity_id": ID}
            ).target_identity_id,
            ID,
        )
        for body in [
            {"operation": "password_add", "new_email": "forged@example.invalid"},
            {"operation": "email_change"},
            {"operation": "google_link", "target_identity_id": ID},
            {"operation": "google_unlink", "target_session_id": ID},
            {"operation": "session_revoke", "target_identity_id": ID},
        ]:
            with self.subTest(body=body), self.assertRaises(ValidationError):
                IdentityTarget.model_validate(body)

    def test_google_start_identity_is_not_a_verifier_claim(self):
        self.assertEqual(
            GoogleChallenge.model_validate(
                {"operation": "password_add", "identity_id": ID}
            ).identity_id,
            ID,
        )
        for key in [
            "owner_id",
            "user_id",
            "revision",
            "verified",
            "iat",
            "nonce",
            "audience",
            "method",
        ]:
            with self.subTest(key=key), self.assertRaises(ValidationError):
                GoogleChallenge.model_validate(
                    {"operation": "password_add", "identity_id": ID, key: "forged"}
                )
        with self.assertRaises(ValidationError):
            GoogleVerification.model_validate(
                {
                    "operation": "password_add",
                    "identity_id": ID,
                    "challenge_id": ID,
                    "challenge_token": TOKEN,
                    "credential": "private",
                }
            )

    def test_email_and_request_tokens_cannot_substitute_for_each_other(self):
        body = {
            "proof_token": TOKEN,
            "request_id": ID,
            "request_token": TOKEN,
            "email_token": "m" * 43,
            "old_email_token": "o" * 43,
        }
        self.assertEqual(EmailCompletion.model_validate(body).request_id, ID)
        for key, value in [
            ("request_token", "m" * 43),
            ("email_token", TOKEN),
            ("old_email_token", TOKEN),
            ("request_id", TOKEN),
        ]:
            with self.subTest(key=key), self.assertRaises(ValidationError):
                EmailCompletion.model_validate({**body, key: value})

    def test_notification_consent_is_strict_and_does_not_include_channels(self):
        body = {"expectedRevision": 1, "in_app_success": False, "preview": "generic"}
        self.assertFalse(NotificationUpdate.model_validate(body).in_app_success)
        for key, value in [
            ("expectedRevision", True),
            ("in_app_success", 1),
            ("preview", "private"),
            ("email", True),
            ("browser_permission", "granted"),
            ("consent", True),
            ("owner_id", ID),
        ]:
            with self.subTest(key=key), self.assertRaises(ValidationError):
                NotificationUpdate.model_validate({**body, key: value})

    def test_password_and_tokens_never_appear_in_dto_repr(self):
        body = PasswordEnrollment.model_validate(
            {
                "proof_token": TOKEN,
                "request_id": ID,
                "request_token": TOKEN,
                "email_token": "m" * 43,
                "new_password": "PRIVATE_PASSWORD_CANARY_389",
            }
        )
        self.assertNotIn(TOKEN, repr(body))
        self.assertNotIn("PRIVATE_PASSWORD_CANARY", repr(body))
        self.assertNotIn("m" * 43, repr(body))


if __name__ == "__main__":
    unittest.main()
