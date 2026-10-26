# Account-mail host operation

`launch.py` is the Linux host entrypoint for one account-mail job. The backend
entrypoint remains `python -m auth.mailworker`; `run_once.py` is its compatibility
wrapper. None of these files installs a scheduler, creates provider credentials,
enables flags or sends a message merely by being checked out.

Run the launcher as the existing `ben2004` Docker operator:

```bash
/usr/bin/python3 -E -s -B /srv/bank-ai/ops/accountmail/launch.py
```

The only environment input is the fixed, separately provisioned
`/home/ben2004/.aqua-runtime/mail/worker.env`. Its directory and parent must be
owned by the operator with mode 0700; the file must be a single-link regular
file owned by the operator with mode 0600. Symlinks, special files, duplicate
keys, shell syntax, unknown keys and oversized/control-character content are
rejected. The worker receives exactly the ten variables named in
`worker.env.example`, with a socket-only `aqua_app_runtime` URL, one connection,
one waiter, a two-second acquisition deadline and `https://aqua-ai.us` as its
canonical origin. `DATABASE_URL`, model settings, Google/session secrets and the
application's full `.env` must never be copied into this file.

Provision the outbox key separately from all other secrets, retain an independent
recovery copy, and use the same key in the web encryption and worker decryption
environments. Keep the existing domain-restricted Resend Sending-access key in
the private mail environment only. Do not broaden it for readiness checks:
Resend's read-only domain, key-management and usage endpoints reject a
Sending-only key with the documented `401 restricted_api_key` response. Domain
verification, domain restriction and provider tracking settings therefore need
operator dashboard evidence or the approved controlled-message checks; this
launcher does not claim to verify them.

The launcher takes a nonblocking owner-only `fcntl` lock and refuses to start
when any labelled managed worker or the fixed container name is already present.
It validates the environment and passes an immutable sealed-memory snapshot to
the Docker CLI through an inherited file descriptor. No secret is put in command
arguments or a temporary disk copy. Docker still stores container environment
metadata for Docker administrators; this is not a boundary against that operator.

Docker access uses only `/usr/bin/docker` and the local
`unix:///var/run/docker.sock`, with a small fixed process environment. Ambient
Docker contexts, proxy settings and credential helpers are not inherited. The
local `bank-ai-backend:latest` tag is resolved once to an immutable image ID;
`--pull=never` prohibits a registry fetch. Release procedures must ensure that
tag identifies the tested, active backend release before enabling the schedule.

Each container runs as UID/GID 1000:1000, on the bridge network with no published
ports, a read-only root filesystem and read-only existing app-DB socket volume.
It drops all capabilities, enables no-new-privileges, disables Docker log storage
and healthchecks, and has 128 MiB RAM, one CPU, 32 PIDs and an 8 MiB noexec tmpfs.
The bridge supplies outbound HTTPS for the fixed Resend adapter; it does not
expose the private database over TCP. The launcher never creates a missing socket
volume, removes a volume, restarts the API or touches the analytical database.

Docker operations have individual deadlines and a shared 55-second work deadline;
an attached worker gets at most 35 seconds within that budget. Cleanup has its
own bounded calls. On timeout, interruption or normal exit, the launcher verifies
the exact container ID, name and both purpose/run labels before removing only
its own container, then independently checks absence. Ambiguous creation,
ownership, daemon or cleanup results fail closed. A later invocation refuses a
leftover worker rather than overlapping it. SIGKILL, a host outage or a lost
daemon can still leave a container; keep the schedule paused until an operator
has reviewed that container and its persisted lease. Never reset attempts, leases
or idempotency keys to force delivery.

`cron.example` is a reviewable once-per-minute schedule. Install it deliberately
in `ben2004`'s crontab after activation prerequisites pass; it needs no user-session
linger setting. Do not install it alongside a second scheduler. The private lock
and database's existing 90-second global delivery lease remain independent
overlap controls. The existing hourly/daily purpose reservations and three-attempt
retry limit continue to apply; the schedule does not multiply quota.

The launcher emits one fixed JSON status: `idle`, `attempted`, `busy`, `disabled`
or `unavailable`. It captures and suppresses child stdout/stderr and never prints
configuration, addresses, message bodies, links, provider responses or exception
text. `attempted` means the bounded worker processed a job, not that an inbox
received it. Review `aqua-account-mail` syslog/journal events for repeated
`unavailable`, and monitor aggregate queue state/purpose counts, attempts and
oldest pending age using the reviewed private runtime role. Alert on repeated
failure, expiry risk and queue/quota pressure without recording recipient/job
identifiers or encrypted envelopes.

To pause sending, set `ACCOUNT_MAIL_WORKER_ENABLED=false` in the reviewed private
worker file and remove/disable only this scheduled entry. Pause new registration
and recovery issuance independently if appropriate; preserve existing password
logins, sessions, pending rows and the outbox key. Re-enabling is an explicit
reviewed configuration action, not an automatic failure response.

New `aqua-account-v1` envelopes persist canonical HTML, plain text, origin,
purpose and template version inside the existing 4 KiB encrypted payload bound.
The provider receives fixed `app`, `purpose` and `template` tags only. No external
images, fonts, tracking resources or user-supplied markup are embedded. Original
three-field plain-text envelopes retain their original request bodies and
idempotency keys. Preserve existing version renderers until their jobs expire;
never silently restyle a pending retry under its original key.

Synthetic launcher regressions are part of `backend/tests/test_account_mail_launcher.py`.
The mail template/adapter/envelope suites use fake addresses and a fake provider.
They make no real delivery calls. Live activation and controlled inbox checks are
recorded separately by the release owner.

Provider references: [Resend errors](https://resend.com/docs/api-reference/errors),
[send body and tags](https://resend.com/docs/api-reference/emails/send-email),
[idempotency](https://resend.com/docs/dashboard/emails/idempotency-keys).
