# Google sign-in and durable AQUA sessions

P03 replaces signed profile cookies with opaque, revocable application sessions
in the private application database. Google establishes an external identity;
AQUA assigns a canonical internal UUID and checks current account, session and
dataset authorization on protected requests. Email equality never links accounts.

**Deployment state:** P02 is live at `5ac90fcca45a6a74bab5d6f792388c05804d87a2`
with storage enabled and schema 1. This P03 source requires schema **2**; its
migration and authentication cutover remain separate reviewed release actions.
Follow [P03 identity cutover](ops/P03_IDENTITY_CUTOVER.md) before starting P03
images. Password login, registration and account-linking UI are later phases.

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
| `APP_STORAGE_ENABLED` | Must be true for P03 authentication |
| `APP_DATABASE_URL` | Dedicated runtime-role socket DSN, supplied by the private storage overlay |

See [private storage operations](../ops/appdb/README.md) for credentials, pool
budgets and socket attachment. Do not use analytical `DATABASE_URL` as an
application-storage fallback. It continues to select the existing read-only
analytical dataset; P03 does not onboard customer databases or change its roles.

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
   issuer/subject is an external mapping. Capabilities currently report
   `durable_sessions: true`, Google availability and `password_login: false`.
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
recovery, linking and session-management screens remain later implementations.
These controls do not claim that session counts alone prevent all server
overload.

## Release verification

Use [the cutover procedure](ops/P03_IDENTITY_CUTOVER.md) for the reviewed merge,
exact images, explicit schema-2 migration, storage overlay, internal readiness
and safe failure handling. Web startup never migrates. Public readiness probes
must stay denied. A healthy `/api/health` alone does not prove authentication
readiness.

Automated fixtures use fake Google verification/models and isolated PostgreSQL;
replay, rate/concurrency and failure exercises stay there. A real Google login
or authenticated analytical query requires its separately scoped operator
check. Do not infer live provider registration, email delivery or off-server
restore success from synthetic tests. Never restore legacy signed-cookie
acceptance as a P03 rollback.
