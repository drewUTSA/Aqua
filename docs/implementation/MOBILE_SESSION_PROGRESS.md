# Mobile session reliability — November 13, 2026

Ben reports iPhone 16 Safari/Chrome showing a session error during email access.
The exact mail-delivery failure was not established. No real verification or
reset messages were sent during this investigation.

## Live ingress correction

The public HTTP site previously served HTTP200 without redirecting, while the
backend's configured origin is `https://aqua-ai.us` and its cookies require
HTTPS. An HTTP visit therefore cannot use the expected secure session normally.
After Ben signed into the existing Cloudflare account locally, Always Use HTTPS
was enabled for the existing `aqua-ai.us` zone. At 20:29:29Z on November 13,
`http://aqua-ai.us/signin?source=https-check` returned HTTP301 with the exact
HTTPS path/query, HTTPS `/` returned HTTP200, and internal readiness remained
ready on schema8. This closes a concrete failure route; it does not establish
that every reported phone failure had the same cause.

No application container, database, key, Google audience, analytical grant or
cookie/CSRF policy changed. The live backend remains the P11a release. HSTS,
preload and subdomain policies were not enabled as part of this targeted fix.

## Source repairs

Cross-engine verification found another concrete fault: `mode: "same-origin"`
combined with `referrerPolicy: "no-referrer"` makes Firefox/WebKit serialize a
mutation's Origin as `null`. The server correctly rejects it. Protected
mutations now use `strict-origin`, so only the origin is sent, with no page
path, query or fragment. GETs retain `no-referrer`; same-origin mode, blocked
redirects, exact server Origin and CSRF checks remain. All retained unit cases
remain; four transport expectations now distinguish reads from mutations.
The browser fixture now enforces exact mutation Origin and origin-only/no
Referer instead of accepting requests irrespective of those browser headers.
A real Firefox red case with the old build was retained before the repair.

- Optional BroadcastChannel construction, messaging and close tolerate storage
  denial. Messages remain metadata-only; authenticated server reads decide
  authority. Existing revocation/owner fences remain in place.
- A persisted pageshow forces session validation even inside the normal focus
  debounce. Offline locks private access; reconnection rechecks without
  replaying prompts or mutations. Ordinary focus preserves signed-out forms.
- Session/login/logout operations have a 30-second deadline. An uncertain
  sign-out stays locked, including through reconnect. Optional Google config
  has its own 15-second deadline and cannot delay the password form.
- Email registration, verification and reset submissions retain their existing
  30-second bounded
  waits, safe feedback and password cleanup. A failed or uncertain mutation is
  never automatically replayed. Reset locks cached identity before and after
  the attempt, including a lost response.
- A successful login response must be followed by an authenticated session GET
  for the same owner before opening the workspace. Missing/blocked cookies or
  an unavailable confirmation leave explicit recovery, never apparent access
  based only on the POST body.
- Google SDK auto-selection cleanup is best effort; browser storage denial
  cannot veto local logout or reset.

Secure, HttpOnly, SameSite=Lax cookies, exact Origin/CSRF checks, idle/absolute
lifetimes, session limits and all existing application budgets are unchanged.

## Verification and remaining acceptance

The 614 retained frontend cases plus eleven new privacy/lifecycle/deadline cases
pass (625 total). Foreground checks preserve the existing wall-clock debounce
contract and recover after backward device-clock correction. Both builds must retain the existing 600,000-byte initial JS
and 80,000-byte CSS ceilings. Additional CI jobs run production builds for both
shells in pinned Chromium, Firefox and WebKit with iPhone 16 emulation, alongside
all nine existing jobs. Fixtures use only synthetic accounts, provider scripts
and mail proofs. Browser engine emulation is not a physical iPhone result.

The additional journeys check storage denial, sign-in/out, offline/reconnect,
persisted-page events, optional-provider stalls, bounded session/logout/reset
waits, deliberate verification, cookie confirmation, reload and cookie loss.
The fixture's actual browser cookie jar is used, but it is loopback HTTP;
production Secure-cookie/TLS behavior also requires the retained real-backend
checks and a physical-device acceptance pass at the canonical HTTPS site.

Google's current [supported-browser guidance](https://developers.google.com/identity/gsi/web/guides/supported-browsers)
requires redirect mode on iOS. The existing popup integration has not acquired
a redirect callback in the first frontend repair. The subsequent
[default-off redirect source](GOOGLE_REDIRECT.md) prepares that transport with
its own backend and browser regressions. Do not claim live Google iOS acceptance or
weaken cookie/CSRF policy to work around it. A separate bounded redirect design
must retain the durable challenge, verified nonce/signature/audience, Google
double-submit protection and same-owner checks, with its exact authorized URI
configured in the existing OAuth client before enablement. Embedded mail-app
WebViews are not supported by Google; use the system Safari/Chrome browser.

The [personal-computer handoff](PERSONAL_COMPUTER_RELEASE_HANDOFF.md) still
governs the source release, backup/recovery and schema9 activation. Do not run a
routine full-stack update to deploy this frontend repair: current main also
contains the unactivated schema9 backend. Read current exact-head and distinct
merged-main CI before release and record physical Safari/Chrome acceptance.
