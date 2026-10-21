# Google sign-in and durable AQUA sessions

P03 replaces signed profile cookies with opaque, revocable application sessions
in the private application database. Google establishes an external identity;
AQUA assigns a canonical internal UUID and checks current account, session and
dataset authorization on protected requests. Email equality never links accounts.

**Deployment state:** P03 is live at `c25a3332e67f644e94c6ab3b6e80155dacf7c56b`
with storage enabled, schema **2** and durable sessions. The observed
[P03 release](implementation/P03_RELEASE.md) supersedes the historical P02 and
P03 deployment-pending notes. This P04 source requires schema **3**; its migration
and deployment remain a new reviewed action. Follow
[P04 password cutover](ops/P04_PASSWORD_CUTOVER.md) before starting P04 images.
Password method, registration, recovery issuance and account mail remain disabled.
P05's complete password/verification/reset browser forms are not implemented;
explicit method linking remains P10.

## Configuration

Keep the actual `/srv/bank-ai/.env` and private storage credentials on the server.
Pull reviewed source and the blank template; never replace an existing private
environment with `.env.example`.

| Variable | Purpose |
|---|---|
| `GOOGLE_CLIENT_ID` | Google OAuth Web application client ID; public, not a secret |
| `SESSION_SECRET` | At least 32 random characters, shared by backend instances; binds nonce/CSRF values |
| `APP_ORIGIN` | Exact browser origin, normally `https://aqua-ai.us` |
| `SESSION_MAX_AGE_SECONDS` | Absolute session lifetime: default 3600, supported 300–86400 |
| `AUTH_IDLE_SECONDS` | Idle lifetime: default 1800, supported 60–3600, capped by absolute expiry |
| `AUTH_MAX_SESSIONS` | Active sessions per account: default 5, supported 1–20 |
| `AUTH_ALLOWED_EMAILS` | Explicit approved verified Gmail/Google Workspace emails |
| `AUTH_ALLOWED_GOOGLE_SUBS` | Explicit approved Google subject identifiers |
| `APP_STORAGE_ENABLED` | Must be true for durable authentication, with the schema required by the deployed binary |
| `APP_DATABASE_URL` | Dedicated runtime-role socket DSN, supplied by the private storage overlay |
| `PASSWORD_AUTH_ENABLED` | P04 method flag; false by default; independent of Google availability |
| `PASSWORD_REGISTRATION_ENABLED` | P04 new-registration issuance flag; false by default |
| `PASSWORD_RECOVERY_ENABLED` | P04 new-reset issuance flag; false by default |
| `ACCOUNT_MAIL_ENABLED` | P04 encrypted outbox integration flag; false by default |
| `ACCOUNT_MAIL_WORKER_ENABLED` | Separate explicit worker activation flag; false by default |

See [private storage operations](../ops/appdb/README.md) for credentials, pool
budgets and socket attachment. Do not use analytical `DATABASE_URL` as an
application-storage fallback. It continues to select the existing read-only
analytical dataset; P03/P04 do not onboard customer databases or change its roles.
Password/mail configuration and the independent outbox encryption key are
described in the [mail runbook](ops/P04_ACCOUNT_MAIL.md); the Resend provider key
belongs only in the separate worker environment, not the web process.

Storage/signing failures make protected authentication fail closed with fixed
503 responses. Missing Google configuration prevents a new Google login but
does not disable an existing valid durable session's `/me` or logout operations.
Liveness remains independent of these dependencies.

For local browser work, use `APP_ORIGIN=http://localhost:5173` and that exact
origin. HTTP is accepted only for supported loopback origins. Production cookies
are host-bound `__Host-` cookies with Secure, HttpOnly, Path=/ and SameSite=Lax;
development HTTP omits Secure. Cookie values contain random `v2.` tokens, not
profile claims, database credentials or Google JWTs. The database stores token
digests, not reusable plaintext session/challenge tokens.

## Google Cloud and production routing

Use an OAuth Web application client. Add `https://aqua-ai.us` to Authorized
JavaScript origins; add the actual localhost origins only for development.
Configure branding, support contact, homepage, privacy/terms URLs and the
authorized domain. The GIS JavaScript callback uses basic identity scopes,
without a Google client secret or redirect/form-post endpoint.
See [Google's GIS setup reference](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid).

Use one canonical browser origin. Adding another Google origin does not change
AQUA's exact Origin/CSRF checks. Keep the public policy pages consistent with
the application's actual behavior.

Production serves a built React site through nginx on `127.0.0.1:5173`.
Both public hostnames enter that nginx origin through Cloudflare Tunnel; nginx
forwards `/api/*` to the backend on `127.0.0.1:8000`. Vite is for development.
Preserve cookies, Set-Cookie, Origin and X-CSRF-Token, and bypass shared caching
for private APIs. Do not route the API hostname directly around nginx.
Only public static assets may use the CDN cache.

Nginx keeps readiness private and applies separate socket-peer budgets to
questions, Google callbacks and challenge bootstrap. Forwarding headers cannot
create fresh quotas. Behind the current local tunnel these are conservative
aggregate budgets, not verified per-visitor IP limits. P03 also uses durable
peer/global/account auth counters shared across workers; P07 adds the wider
analysis/global admission lifecycle.

## Browser contract

The integration is in `useGoogleAuth.js`, `authClient.js` and
`googleIdentity.js`. Use relative same-origin API URLs, credentials
`same-origin` and cache `no-store`. Keep returned CSRF/profile state in memory;
never persist Google credentials or session tokens in browser storage.

1. Fetch `GET /api/auth/config`. It returns `client_id`, `nonce`,
   `csrf_token` and boolean `capabilities`, and sets an opaque HttpOnly login
   challenge cookie. The durable challenge expires after 600 seconds.
2. Initialize GIS using that client ID and nonce, render its official button,
   and receive the ID token through the JavaScript callback.
3. POST `{"credential": credential}` to `/api/auth/google` with JSON content
   type and the config X-CSRF-Token. The browser supplies Origin. AQUA checks
   the browser binding, atomically consumes the challenge and commits callback
   admission before contacting Google. No DB transaction remains open during
   token verification.
4. Verification checks signature, audience, issuer, lifetime and nonce. A new
   opaque session and session-bound CSRF value are issued only after canonical
   identity, current account state, account budget and atomic session-cap checks.
   Every failed callback needs a fresh config/challenge/nonce before retry.
5. Success and `GET /api/auth/me` return
   `{user: {id, email, name, picture}, csrf_token, can_query, capabilities}`.
   `user.id` is the internal UUID used for frontend account state; Google
   issuer/subject is an external mapping. The deployed/default-disabled state
   reports `durable_sessions: true`, Google availability and
   `password_login: false`. P04 reports password availability from its separately
   enabled server method flag; a boolean capability does not create the missing
   P05 forms or authorize opening registration.
6. For `POST /api/query`, send the session X-CSRF-Token and
   `{"question": prompt}`. Current session/account/epoch/grant checks precede
   schema, cache and model work. Query execution, retrieval and cache identity
   use the same server-configured dataset and provider context.
7. POST `/api/auth/logout` with the session X-CSRF-Token. AQUA commits durable
   revocation before returning 204 and deleting cookies. Then clear frontend
   private state and disable Google auto-selection. A copied cookie now fails.
   This does not revoke the user's Google account authorization.

If logout returns 503, revocation was not confirmed: keep account state/drafts,
lock the workspace and offer an explicit retry. Do not report successful logout
or silently resume queries. After confirmed logout or an invalid session, clear
the prior account's visible private state. Delayed responses from an older
account/logout attempt must not restore it.

| Status | Browser meaning |
|---|---|
| 401 | Invalid login proof/session; obtain a fresh sign-in attempt |
| 403 | Origin/CSRF/challenge or dataset-access denial; show the appropriate action |
| 422 | Invalid request; fixed diagnostic without reflected credential/prompt input |
| 429 | Auth budget/session cap reached; respect Retry-After |
| 503 | Storage/configuration/provider/revocation unavailable; preserve accurate state |

Auth/private API responses use Cache-Control: no-store. Do not automatically
replay a private query after an authentication failure. Explicit local
`VITE_AQUA_DEMO_MODE=true` uses fictional data without live auth/query calls;
leave it disabled in production.

## Authorization, expiry and limits

An authenticated account without a dataset grant receives `can_query: false`;
it is not an authentication failure. Fresh verified identities may preserve an
existing explicit subject approval, or authoritative Gmail/Workspace email
approval, with recorded provenance. Third-party Google emails require explicit
subject approval. There is no grant for arbitrary registration, no account
creation from allowlist strings and no linking by matching email. A revoked grant
is never recreated by logging in again. Current allowlists and durable grant
state/version are checked on protected operations.

Defaults allow five active sessions per account, 1800 seconds idle and 3600
seconds absolute lifetime. Accepted state-changing activity can extend idle
expiry within absolute expiry; `/me` polling does not. Concurrent logins share
one atomic account cap. Logout, revocation, disablement and auth-epoch changes
invalidate subsequent use of copied cookies. Changing the signing secret
invalidates existing browser bindings; treat rotation as an explicit
reauthentication event.

P03 stores only owned default preferences; customization remains P09. Password
backend flows are prepared by P04, their browser journeys by P05, and linking
and session-management screens by P10.
These controls do not claim that session counts alone prevent all server
overload.

## Prepared P04 password contract

This is a backend contract for review and P05 integration, not a live password
launch. Every unsafe operation obtains a fresh
`GET /api/v1/auth/bootstrap?action=...` proof for its exact action, then sends
the returned X-CSRF-Token and matching browser cookie/Origin with its POST.
The independent password bootstrap is single-use and cannot be substituted for
the Google login challenge or another password action. Link GET requests and
mail scanners never establish an account, consume final confirmation or reset
a password.

| Action | POST route | JSON body | Success |
|---|---|---|---|
| `registration` | `/api/v1/auth/registrations` | `{email}` | Generic 202 for eligible/ineligible mailboxes |
| `verification` | `/api/v1/auth/email-verifications` | `{token,password}` | 204; return to ordinary sign-in |
| `login` | `/api/v1/auth/password-login` | `{email,password}` | Canonical user/session response, matching the Google facade |
| `reset-request` | `/api/v1/auth/password-reset-requests` | `{email}` | Generic 202 for eligible/ineligible mailboxes |
| `reset` | `/api/v1/auth/password-resets` | `{token,password}` | 204; no automatic login |

Registration requests take **only an email**. An account/password is created
transactionally only when a mailbox token meets the recipient's freshly chosen
password; clicking a link never activates an attacker's earlier password.
Pending requests expire without reserving a canonical account/address. Email
equality never links a Google account, and unauthenticated reset cannot create
the first password for a Google-only account. Existing-session checks and
password login remain independent of Google availability; password login also
does not require mail delivery.

P04 supports ASCII mailboxes with deliberate case-insensitive keys, preserving
dots and plus suffixes. It does not silently rewrite existing Google keys or add
internationalized aliases. Passwords use consistent NFC normalization, 15–128
normalized characters, up to 512 UTF-8 bytes, a pinned offline common-password
blocklist and bounded Argon2id work. No submitted password is sent to an external
breach service. Registration grants no financial-data permission.

Verification/reset tokens are single-use, purpose/address-bound and digest-only
in challenge records. Retryable mail stores an encrypted recipient/link with a
separate key, bounded delivery attempts and prompt ciphertext retirement.
Reset advances the account epoch, revokes usable sessions and outstanding reset
proofs atomically, and queues a security notice. The browser must clear private
account state after confirmed reset and use the normal sign-in flow. A copied
old session cannot regain access.

P05 must implement `/verify-email#token=...` and `/reset-password#token=...` forms:
move the fragment into private memory, clear it promptly, suppress referrer and
analytics leakage, and never log or reflect it. Complete both login methods and
recovery/error/retry journeys before enabling the issuance flags. Follow the
[activation gates](ops/P04_PASSWORD_CUTOVER.md) and
[mail isolation/fairness procedure](ops/P04_ACCOUNT_MAIL.md); no scheduler or
additional real email is authorized by this documentation.

## Release verification

The [P03 release](implementation/P03_RELEASE.md) records the completed schema-2
cutover and actual checks. For pending P04 use the
[P04 cutover procedure](ops/P04_PASSWORD_CUTOVER.md): verify the reviewed merge,
exact images/corpus, a fresh encrypted pre-change backup, explicit schema-3
migration, storage overlay, internal readiness and safe failure handling. Do not
rerun bootstrap over the installed database. Web startup never migrates. Public readiness probes
must stay denied. A healthy `/api/health` alone does not prove authentication
readiness.

Automated fixtures use fake Google verification/models and isolated PostgreSQL;
replay, rate/concurrency and failure exercises stay there. A real Google login
or authenticated analytical query requires its separately scoped operator
check. Do not infer live provider registration, email delivery or off-server
restore success from synthetic tests. Never restore legacy signed-cookie
acceptance as a rollback. After schema 3 commits, a schema-2 P03 binary is not
compatible: keep the new flags disabled and use a reviewed compatible forward
fix or maintenance. Recovery uses matching software/schema with **all** auth/mail
workers detached before applying its reviewed fence; P04 fencing invalidates
restored sessions/proofs, clears only retired hash slots and cancels/wipes pending
mail without resetting spent delivery quotas. The historical schema-1 backup is
not evidence of a current P04 backup or a successful production restore.
