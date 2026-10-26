# P05 production activation — October 26, 2026

The user requested production email/password activation, AQUA-branded account
emails, and completion of P06 in one supervised run. P07–P13 are excluded.
Use separate reviewed PRs and passing required checks for activation and P06;
apply the private application migration only after its own backup and tests.
This authorization does not change Google approvals or analytical-data grants.

## Candidate behavior

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

## Verification and pending production gate

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

Required full candidate/remote checks, deployment, sender/inbox proof, schedule
installation and public flags are still pending. A Sending-access Resend key
correctly cannot inspect domains, tracking configuration or account limits;
the observed restricted-key response does not establish those facts. Controlled
received-message checks must establish sender authentication, direct trusted
links and actual receipt. No provider key broadening is required.

## Controlled activation and recovery

The approved live exercise is one verification, one reset email and one
password-change notice to the operator's chosen inbox, using a fresh plus alias
to avoid changing an existing Google-only account. Use at most 25 auth HTTP
requests, a loopback-only canary API, no model/business queries, and manual
one-job worker invocations before installing the normal schedule. Do not print
or retain plaintext test passwords, cookies or bearer values. Stop on unexpected
state, authentication, delivery, budget or cleanup failure. Synthetic attack,
load, fairness and replay exercises remain in isolated fixtures.

After inbox and lifecycle proof, enable password login, registration, recovery
and web outbox encryption deliberately. Enable delivery only in the separate
worker environment; the web receives no provider key and starts no worker.
Preserve Google configuration, sessions, account epochs and dataset grants.
Record actual image IDs, flag states, scheduler state, public checks and cleanup
in the final release checkpoint before claiming production activation complete.

Pause worker delivery and new issuance independently on failure, retaining the
outbox key, pending records and durable security state. Preserve working login
and revocation where possible. Use a schema-compatible forward fix or
maintenance; do not restore the vulnerable telemetry pin or reset delivery
attempts/leases to force mail through.
