# P04 PR — password authentication and bounded account mail

AQUA now has backend email/password registration, verification, login and recovery alongside Google. Registration first proves mailbox ownership and establishes a fresh password, preventing attacker pre-registration; reset requires an existing password credential and never links a Google-only identity by matching email. Password sessions use P03's canonical accounts, durable revocation and dataset authorization, with transactional reset/epoch invalidation.

Argon2id work has shared admission and two global hash slots, and the shipped common-password corpus is pinned, licensed and integrity checked. A transactional AEAD-encrypted outbox uses bounded retries, stable provider idempotency, fenced leases and separate registration/recovery/security queue and delivery capacity. New nginx zones limit password and mailbox flows before backend work. All password/signup/recovery/mail flags remain disabled by default; no real mail, worker schedule, public signup or production migration is activated.

## Schema and operational review

- Additive schema 3; original schema 1/2 migration checksums remain unchanged. Migrate with the reviewed new image before starting schema-3 code.
- Request hashing releases DB leases. A crashed hash slot fails closed; recovery stops all hash-capable workers before clearing proven retired slots. Restore fencing cancels old sessions/challenges/mail and retired slots before reconnecting workers.
- P05 supplies the login/verification/reset UI and complete browser journey. Explicit linking and password change/add/unlink remain P10 work. New accounts receive no analytical grant.
- [Implementation and evidence](P04.md), [password cutover](../ops/P04_PASSWORD_CUTOVER.md), [account-mail worker](../ops/P04_ACCOUNT_MAIL.md).

## Validation

1056/1056 backend cases pass across bank/Pagila, including three-process global hash admission, takeover/replay/reset revocation, mail fairness/outage and limiter recovery. The exact frontend image passes 98 bounded proxy requests with zero rejected upstream work and cooldown recovery. 71 frontend tests and production build pass. Actual-image schema 3 installer/SCRAM/repeated migration/export and synthetic restore/epoch/hash/mail fences pass; temporary resource absence is confirmed.

All 67 packaged runtime/assets plus nginx match reviewed hashes; pip check, Black/Ruff, lock/source/corpus/license guards pass. Current 49-package Python and frontend advisory audits report no known vulnerabilities. Retained red findings include malformed-hash fast denial, corpus/test packaging and fixture errors; paired fixes pass. 32 samples measure Argon2 cost only, not full production capacity. See `evidence/p04` for exact images/results. Shared anonymous bootstrap quotas can still throttle legitimate sign-in/recovery under flood; independent POST/mail allocations are the scoped guarantees.

Tests use isolated synthetic databases and fake Google/model/mail transports. Real delivery, production restore, browser password forms and representative production capacity are not claimed. P03 remains the deployed release at schema 2; review/merge and later explicit cutover are separate checkpoints.

## Follow-up security closure

Recipient cooldown/rolling daily history and pending-message coalescing survive deletion/restart. Fixed templates and proof bindings constrain mail content. Custom SQL operator/type/catalog-cast paths, automatic Markdown network elements and spreadsheet clipboard formulas are closed with paired regressions. Fourteen isolated real-browser renderer payloads produce zero external attempts or handler execution. See [P04_SECURITY_REVIEW.md](P04_SECURITY_REVIEW.md). No real mail or production attack was performed.
