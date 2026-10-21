# Add canonical accounts and durable, revocable Google sessions

Replace signed profile cookies with opaque sessions backed by the private app
database. Resolve verified Google identities to internal UUIDs, make login
challenges single-use, and check current account state, epoch and dataset grants
on protected requests. Add atomic active-session caps and durable peer/global/
account login budgets so additional cookies or workers do not reset quotas.

Adapt the frontend identity contract and preserve locked drafts/results until
logout is confirmed. A canonical account change or confirmed 401 clears private
state and aborts old requests. Keep Origin/CSRF/cookie protections and suppress
submitted credentials in validation errors. Google availability no longer gates
existing durable-session validation or logout.

Validation:

- 54 offline frontend tests, 44 synthetic browser checks and production build pass.
- New contract tests expose 9 failures against unchanged P02 code and pass with P03.
- 835/835 backend cases pass across bank/Pagila; 48-request proxy abuse/recovery checks pass with no rejected upstream work.
- Actual-image installer/SCRAM/repeated migration, runtime denials, export and synthetic restore/epoch fences pass; temporary resources removed.
- Candidate `sha256:d53579ff00ac742e817076b2a1dce7b6afd1876d382b69a58c94ab3e4cc29a2d`: 43 packaged files match reviewed hashes, pip check/Black/Ruff/lock/source guards pass.
- Current Python/frontend audits report no known vulnerabilities; no dependency changes. See `docs/implementation/evidence/p03` for red findings and passing retests.

P03 is not deployed. Its reviewed cutover explicitly migrates to schema 2 and
forces existing users to reauthenticate; there is no legacy cookie fallback.
Preserve DB volumes/credentials and use a compatible durable-session release or
forward fix if rollback is needed. See `docs/implementation/P03.md` and
`docs/ops/P03_IDENTITY_CUTOVER.md`.

Password flows remain P04, global AI job admission P07 and session-management UI
P10. The hosted analytical DB is unchanged. These scoped synthetic checks do not
claim a complete production penetration test or real off-server restore.
