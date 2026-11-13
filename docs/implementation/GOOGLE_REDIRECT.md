# Prepared Google redirect transport — disabled by default

This source prepares Google's documented redirect mode for iOS and other
supported browsers. It is not a deployed callback or a successful live Google
acceptance claim. `GOOGLE_REDIRECT_ENABLED` defaults to `false`. The independent
email/password method remains available while Google is unavailable.

On November 13 Ben signed into the existing `aqua-ai` Google project locally.
The existing client's ID was matched to the running application's public ID;
`https://aqua-ai.us/api/auth/google/redirect` was added, saved and verified by
reopening the client. Its existing `https://aqua-ai.us` JavaScript origin was
preserved. No secret was created/rotated and no audience or scope was changed.
Google's console warns of five minutes to several hours of propagation.
This completes console preparation, not application activation or phone acceptance.

## Browser and server contract

When explicitly enabled on an HTTPS origin, the existing config response adds
only `redirect_path: /api/auth/google/redirect`. The client accepts that exact
path, constructs its own origin URL and initializes GIS with `ux_mode: redirect`,
the existing client ID/nonce and no popup callback. No caller return URL, new
OAuth client secret, public audience or new scope is involved. Without the
flag, the original callback mode and response shape remain.

`POST /api/auth/google/redirect` accepts a bounded Google form or JSON body
containing credential, Google CSRF token and optional matching client ID. It
rejects duplicates, unknown fields, query parameters and oversized bodies.
Reading the body has a total ten-second deadline, including a chunked stream;
timeout/oversize rejection occurs before any challenge consumption or identity work.
The callback document makes no authentication mutation, issues no cookie,
consumes no challenge and calls no provider. It can receive a navigation with
missing Lax cookies or `Origin: null`. That allowance ends at the inert document;
it is not accepted by the authenticated completion.

The response has no-store/no-referrer, frame denial and a response-local nonce
CSP allowing only its own script and same-origin connections. The credential
stays out of URLs, storage and diagnostics. The script removes its own DOM node,
uses one 30-second deadline and clears its payload after completion/page hide.
It does not retry an uncertain POST automatically. Manual links check the
session or return to sign in.

Once this is a first-party document, the browser can return the original Lax
host-bound challenge cookie. `GET /api/auth/google/redirect-state` derives the
same existing CSRF value without rotating or consuming that challenge. It
requires unambiguous challenge and Google CSRF cookies. Its response is private
and uncacheable; no CORS access is granted.

The script then makes exactly one `POST /api/auth/google/redirect-complete`.
The server checks Google cookie/body double-submit equality and rejects
duplicate cookies before calling the original login implementation. That
implementation still requires exact APP_ORIGIN and the original header CSRF,
durably consumes the one-use challenge before verification, checks signed
Google identity/audience/nonce and current account policy, then creates the
ordinary durable session. Provider work stays off the ASGI event loop and
outside the DB lease. Completion does not add analytical access or link by email.

Successful completion navigates to `/`, where the normal session GET decides
access. Cookie absence, CSRF/nonce failure, provider failure and timeout never
open the workspace on the strength of a POST body alone. Cookies remain
Secure/HttpOnly/SameSite=Lax, with no Domain attribute or lifetime extension.

Protected same-origin fetch mutations use `strict-origin` referrer policy:
Firefox/WebKit otherwise serialize Origin as null under `no-referrer` in this
mode. Only the origin is disclosed; paths, queries and fragments are excluded.
The document itself retains no-referrer. Server Origin/CSRF defenses stay strict.

## Exact operator configuration and activation

1. Follow the [personal-computer release handoff](PERSONAL_COMPUTER_RELEASE_HANDOFF.md).
   Current main also contains schema9; do not deploy the whole stack as a
   shortcut for this auth repair. The fresh backup/recovery gates remain.
2. In the existing Google OAuth Web client that matches production's public
   `GOOGLE_CLIENT_ID`, retain all existing origins/redirect URIs and add exactly
   `https://aqua-ai.us/api/auth/google/redirect` as an authorized redirect URI.
   No trailing slash, wildcard, callback on HTTP or caller-controlled return URL.
   Keep audience, consent/scopes, allowlists and grants unchanged.
3. Deploy only a qualified source/image after every required exact-head PR and
   distinct merged-main job passes. The current native image has 196 compiled
   files, 199 app files and one lock file; its exact inventory and disposable
   recovery receipts are in [the evidence directory](evidence/mobile/).
4. Enable `GOOGLE_REDIRECT_ENABLED=true` only after that exact URI is authorized
   and the source is running. Restart through the reviewed release procedure;
   retain private environment, storage, mail singleton and protected authority.
5. Verify a restricted account on physical iPhone Safari/Chrome and current
   desktop Chrome/Edge, Firefox and Safari: deliberate Google sign-in, cookie
   restore/reload, sign-out, revoked/expired session, offline/reconnect, and
   independent password/verification/reset. Do not send real account-action
   messages or change credentials merely to simulate a browser test.
6. Keep the flag off if the callback cannot be qualified. A fallback to the
   original popup does not establish Google iOS compatibility. Embedded app
   WebViews are unsupported by Google; open the system browser.

Automated engine tests use only synthetic provider UI/accounts and the exact
production document/CSP. Backend attacks use real disposable private PostgreSQL
and mocked Google verification. They do not prove real provider-console setup,
physical iPhone behavior, encrypted independent retention or total-host recovery.

The preceding complete isolated backend matrix passed all 1,897 unique cases across bank
and Pagila fixtures, including the retained capacity case, restore/privilege
checks and all 39 added redirect cases, with cleanup confirmed. All 630 frontend
unit cases pass. Both interface builds pass their unchanged delivery ceilings;
54 synthetic browser journeys per shell passed across the three engines before
the final retained foreground-clock correction. Exact-head and merged-main CI
must qualify the final source. See [the backend receipt](evidence/mobile/backend-matrix.json)
and [native receipts](evidence/mobile/native-qualification.json). That backend
receipt predates the final body-read deadline. Two additional stream/deadline
cases raise the final matrix to 1,899; its fresh-output rerun and exact-head CI
must pass on the current bounded runtime before integration. An earlier local
rerun passed all core and capacity cases but correctly refused to overwrite an
existing evidence file; that run is not reported as a complete matrix pass.

References: [Google browser support](https://developers.google.com/identity/gsi/web/guides/supported-browsers),
[GIS initialization and redirect URI](https://developers.google.com/identity/gsi/web/reference/js-reference),
[server verification and double-submit](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token),
[browser referrer policy and Origin](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy).
