# Account response privacy

Security review item 9, November 25, 2026.

Starting an email change returns the same accepted response shape for a free
target, a target owned by another account, or the account's current primary
address. Each request receives an ordinary opaque request identifier, secret and
expiry and consumes the same bounded pending-request capacity. The response
does not indicate whether the target belongs to another account.

An occupied foreign target or unchanged primary address receives no mail and no
confirmation challenges. Such a pending request cannot complete, even if that
address becomes free later. The existing proof, session binding, expiry, capacity
and both-mailbox checks still apply. Switching back to an existing nonprimary
address belonging to the same account retains its established confirmation
workflow. A collision after legitimate confirmation remains a conflict; accounts
are never merged.

This is an HTTP response guarantee. As required by the no-mail policy, the
requester can observe the absence of a confirmation at their own old mailbox.
It is not a claim that mailbox delivery is indistinguishable.

Generic password registration and recovery mail requests use the same 500 ms
minimum response time for known, unknown and suppressed recipients. Padding runs
after the database transaction releases its connection. Existing admission
limits remain in place and rejected floods are not padded. If database work
exceeds this floor, elapsed time can differ; this is not a constant-time claim.
External mail delivery stays in the encrypted outbox worker.

Regression evidence:

- `backend/tests/test_identity_email_privacy.py` checks the accepted response,
  zero tickets/mail for occupied targets, unchanged accounts, invalid-confirmation
  denial and the same three-pending-request cap.
- `backend/tests/test_identity_mail_actions.py` retains the complete
  two-mailbox, rollback and concurrent-claim checks.
- `backend/tests/auth/test_password_routes_availability.py` measures the actual
  known/unknown registration and recovery routes, with database admission and
  encrypted enqueue enabled. Each observed response must take at least 495 ms,
  and the two medians must remain within 50 ms.
