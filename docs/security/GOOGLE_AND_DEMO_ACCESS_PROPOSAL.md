# Google account creation and synthetic banking access

**Proposed for owner approval.** These are two independent access decisions.

## Google account creation

Make new Google accounts invitation-only when the invitation setting is absent or empty. A configured list would admit only an authoritative verified mailbox matching a normalized invitation. Aqua currently treats an absent setting as open registration. The decision occurs after looking up the verified issuer and subject, so an existing active linked account could still sign in after its invitation expires. Existing account linking protections and the separate dataset grant continue to apply. Password account creation has its own policy.

The following proposed source diff also closes direct account-resolution calls that omit the invitation policy.

```diff
--- a/backend/auth/config.py
+++ b/backend/auth/config.py
@@ -44,4 +44,6 @@
     max_admission_keys: int = 2048
     cleanup_batch: int = 64
-    google_registration_invites: frozenset[str] | None = field(default=None, repr=False)
+    google_registration_invites: frozenset[str] = field(
+        default_factory=frozenset, repr=False
+    )
     previous_history_dataset_key: str = field(default="", repr=False)
@@ -87,5 +89,5 @@
     env = os.environ if environ is None else environ
     try:
-        invites = None
+        invites: frozenset[str] = frozenset()
         if "AUTH_GOOGLE_REGISTRATION_INVITES" in env:
             from auth.password_policy import normalize_email
--- a/backend/auth/accounts.py
+++ b/backend/auth/accounts.py
@@ -89,6 +89,8 @@
     email, authoritative = provider_observation(identity)
     if owner is None:
-        if registration_invites is not None and (
-            not authoritative or email not in registration_invites
+        if (
+            not registration_invites
+            or not authoritative
+            or email not in registration_invites
         ):
             raise AuthDenied("registration_unavailable")
```

If approved, update the current configuration test to require an empty invitation set when the variable is absent. Add a new-account request with the variable absent and verify zero new accounts or sessions. Exercise listed, unlisted and non-authoritative mailboxes, returning previously linked accounts, and an invited user without a dataset grant. An installation relying on open Google signup would need an explicit invitation list before enabling new registrations.

## Synthetic banking reports and calculators

The demo defaults off. When enabled, its synthetic report and calculator service checks the current account and session before reading and again before returning the result. The host-configured demo persona controls which reports and calculations that employee can use. The current service deliberately permits a demo-only employee with no analytical dataset grant.

For a shared deployment, **recommend requiring both an active dataset grant and the appropriate banking persona**. If approved, both transaction checks in `backend/bank_demo/service.py` would use `guard(..., data=True)`. This would also deny demo-only seats access to fictional reports and standalone calculations. Test enabled and disabled hosting, grant present and absent, revoked grants, and personas with and without the requested capability.

The owner can approve the Google default and the additional banking grant separately.
