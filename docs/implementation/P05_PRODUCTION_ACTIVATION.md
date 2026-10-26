# P05 production activation — October 26, 2026

The user requested production email/password activation, AQUA-branded account
emails, and completion of P06 in one supervised run. P07–P13 are excluded.
Use separate reviewed PRs and passing required checks for activation and P06;
apply the private application migration only after its own backup and tests.
This authorization does not change Google approvals or analytical-data grants.

Production activation is complete at server commit
`2f163e01d6477af8a8444a6f36a1d632cfe7b324` (PR #45). P06 has its own
implementation and release checkpoint; completing activation does not claim
that P06 or later phases are deployed.

## Activated behavior

New `aqua-account-v1` envelopes persist canonical HTML and plain text together,
including purpose, origin and version, inside the existing encrypted outbox.
The HTML uses the AQUA wordmark, a purpose label and a trusted verification,
reset or recovery action. It loads no images, fonts, scripts or tracking assets.
Provider tags contain only fixed app/purpose/template categories. The largest
measured encrypted envelope is 2,405 bytes, below the existing 4 KiB limit.
Original three-field envelopes retain their original provider request bodies,
without HTML/tags, so a retry never changes content under an idempotency key.

The Linux operator launcher uses ten explicitly allowlisted worker variables,
owner-only files, a sealed in-memory environment and a singleton lock. It
resolves the tested local backend tag to an immutable image, permits no pull,
and runs one job as UID/GID 1000 with a read-only socket/root filesystem,
128 MiB memory, one CPU, 32 PIDs and no capabilities. It verifies ownership
before cleanup and confirms absence. The once-per-minute cron reference emits
only fixed aggregate statuses to the system logger. It installs nothing by
being checked out. See [the worker runbook](../../ops/accountmail/README.md).

## Verification

- All 96 focused mail and launcher cases passed in an offline Linux fixture.
- Black, Ruff, source/whitespace guards passed for the candidate files.
- An actual Docker/sealed-memory smoke used a fake worker and a newly created
  empty socket volume. It passed and confirmed container/volume removal; it
  used no application database or real provider.
- The three synthetic templates were rendered locally for visual review.
- A fresh schema-3 private-database snapshot was streamed directly to encrypted
  off-server storage after the user approved its sensitive contents and exact
  destination. Authenticated decryption matched the export, the independent
  recovery identity was verified, and no plaintext dump was written. This is
  snapshot integrity verification, not a production restore or measured RPO/RTO.

Local synthetic evidence is under `.check-results/p05-activation/email-previews/`.
The encrypted backup and credential-free report are under
`.check-results/p06-release/`; its identity is separately protected in local
AppData, with an encrypted recovery copy. Never commit or print private keys,
runtime environments, recipients, passwords, bearer links or database contents.

PR CI run `40415408132` and merged-main CI run `40416452369` passed all steps.
The final matrix passed all 1,129 cases; the disposable installer and recovery
checks also passed. The 67-file deployment source comparison passed after CRLF/LF
normalization only. No broader data grant or Google approval was added.

A Sending-access Resend key correctly cannot inspect domains, tracking
configuration or account limits; its restricted-key response establishes none
of those facts. Actual received-message checks supplied the delivery evidence
below, without broadening the provider key.

## Completed controlled activation

The approved live exercise delivered one verification email, one reset email
and one password-change notice to the controlled inbox through a fresh plus
alias. All three reached Gmail INBOX and contained both plain text and HTML,
direct trusted AQUA links, and no remote assets. The received headers reported
DKIM PASS for `account.aqua-ai.us` with account-domain alignment and SPF PASS.
No DMARC result was present, so this checkpoint makes no DMARC claim. The
sanitized receipt report is
`.check-results/p05-activation/live-receipts.json`; it contains no bearer links.

The loopback-only canary completed all four auth-probe phases in 18 HTTP
requests, below the hard ceiling of 25. It proved verification, password login,
reset redemption, rejection of the old password and session, new-password
login without a dataset grant, and logout followed by rejection of the test
session. Exactly three manual one-job worker invocations preceded scheduler
installation. No model or analytical query ran, and no unrelated account was
changed. The canary was removed and its absence confirmed. Only the encrypted
current test password and controlled-account metadata remain for the separately
scoped P06 smoke; passwords, cookies and bearer values were not printed or
stored as plaintext. Synthetic attack, load, fairness and replay exercises
remain isolated fixtures.

After this proof, production enabled `PASSWORD_AUTH_ENABLED`,
`PASSWORD_REGISTRATION_ENABLED`, `PASSWORD_RECOVERY_ENABLED` and
`ACCOUNT_MAIL_ENABLED`. The web worker flag remains false, and the web process
has no provider key. Delivery uses the separate private worker environment.
The deployed immutable backend image is
`sha256:fe8da574799c10b24c15ecf29f09f7eff5f2010f297f9959a4d312f39043756c`,
in container
`7836cf83c733c09badff9e1a53f1881c60ca4e4f4c9955120882282306ca7fe3`.
The existing frontend and schema-3 private database were retained. Public
configuration reported password login enabled; registration and reset-request
bootstrap checks returned HTTP 200.

The scheduler installer passed, and read-only inspection confirmed exactly one
expected once-per-minute cron entry. Cron, journald and rsyslog were active.
The cron journal recorded the scheduled AQUA command at 23:12:01 UTC on
October 26, 2026; the `aqua-account-mail` journal recorded its fixed aggregate
`idle` status at 23:12:02 UTC under the operator UID. This proves an actual
scheduled invocation, with no manual diagnostic worker run or environment read.
Normal operational review should continue to inspect these aggregate statuses;
this release does not claim an active email-alerting service.

## Recovery

Pause worker delivery and new issuance independently on failure, retaining the
outbox key, pending records and durable security state. Preserve working login
and revocation where possible. Use a schema-compatible forward fix or
maintenance; do not restore the vulnerable telemetry pin or reset delivery
attempts/leases to force mail through.
