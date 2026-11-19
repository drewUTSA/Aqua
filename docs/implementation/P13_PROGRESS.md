# P13 launch preparation — November 13, 2026

## November 19 packaged frontend and public site

Both packaged interfaces passed a separate **Try again** browser check. Desktop WebKit received a controlled gateway timeout and showed the fixed employee message. One click on the visible, keyboard-focusable button retried the same original input and displayed the expected count of 19. Reopening the conversation preserved the failed response and the successful retry in the same three-message chat. The controlled provider received exactly two calls per shell. The signed-out session received 401 and another signed-in employee with the same dataset grant received 404 for the private conversation and retry result. [Browser verification](evidence/p12/presenter-and-browser-20261119.json)

From the timeout-handling ZIP, desktop WebKit 27.2 ran an employee through each packaged website over private HTTPS. Both layouts showed the seven expected report rows and citation, retained a private prompt after reload and reopened the exact count of 62 from the employee’s recent chats. After sign-out, profile, history and prompts each returned 401. Both browsers reported zero uncaught page errors and released their test containers and networks. The real identity provider, public origin and intended physical devices remain rollout checks. [Employee browser evidence](evidence/p12/employee-timeout-20261119.json)

On both packaged sites, Nginx now returns the private sitemap's ten-byte plain-text 404 body with the correct content type. The image's normal MIME map had labeled the response as XML. After reload, each image passed all 14 route checks and 24 hashed-asset checks. A separate private HTTPS rehearsal ran 22 requests per shell. It verified the host certificate, HTTP redirect, HSTS and preservation of the origin's headers, including a private readiness response and a real 502 when the backend was unavailable. The temporary ingress issued HSTS for five minutes. Public ingress verification remains part of rollout. [Website fix](https://github.com/drewUTSA/Aqua/pull/100) · [Package and rehearsal identities](evidence/p11bc/sitemap-rehearsal-20261119.json)

Desktop WebKit 27.2 then exercised both shells over verified private HTTPS with fictional accounts. On each shell the employee signed in, opened a report, saw all seven expected rows and their procedure citation, saved a private prompt, reloaded the page and reopened the saved text. After sign-out both private endpoints returned 401. Both browser runs reported zero uncaught errors. Physical-device and intended-user acceptance remain part of rollout.

The three-seat WebKit walkthrough exposed a results pane in which “Download CSV” and “Show full precision” broke across several lines. The table heading and actions now wrap to separate rows when needed. The revised Opal and Legacy packages were archived, each image was restored, and all 14 document routes and 24 expected assets per shell were served again. Both builds retain the branded 404. [Toolbar change](https://github.com/drewUTSA/Aqua/pull/98) · [Revised rehearsal kit identities](evidence/p11bc/toolbar-rehearsal-20261119.json)

In the original Opal walkthrough the presenter saw the correct count in 28.498 seconds and the correct amount bands in 13.786 seconds. Subsequent browser assertions in that run failed. In a fresh replay, WebKit 27.2 reopened both saved answers on the revised interface using the same SQL and fictional data. The three employee sessions completed the chart, cited facts, private note, reconciliation, history and sign-out checks. At a 374-pixel card width all three table actions sat below the title, with readable labels and 44-pixel button heights. The mobile seat used a simulated touch viewport. A separate geometry check passed for both interfaces at 1480, 390 and 320 pixels, with normal and doubled text and a visible keyboard focus ring. [Browser and scope measurements](evidence/p11bc/toolbar-rehearsal-20261119.json)

In the earlier PR 95 rehearsal, both Opal and Legacy were restored from their saved image archives after their local image registrations were removed. Each restored Nginx server served all 14 checked document routes and all 24 expected static assets. The stock error-page URL returned Aqua’s 404 page. An ordinary API request without an available upstream still returned 502 with caching disabled. Docker retained its local layer cache. [Frontend change](https://github.com/drewUTSA/Aqua/pull/95) · [Image and archive identities](evidence/p11bc/local-rehearsal-20261119.json)

The November 19 public observation found HTTPS working on the apex. Home and sign-in omitted HSTS and CSP, robots and sitemap returned the HTML shell, and the www hostname did not resolve from the observing client. The live stack was healthy on schema 8. Production rollout, ingress verification, sign-in and callback, employee assistive use and physical device acceptance remain open. [Public delivery check](P13_PUBLIC_DELIVERY_CHECK.md) · [Current handoff](../../AQUA_CODEX_HANDOFF.md)

**Decision: NO-GO for production cutover or public expansion.** Ben moved the
recovery-key discovery, backup/recovery and release execution to his personal
computer. The application remains on its healthy P11a/schema8 release. Code,
merged status, deployment and enablement are separate claims.

## November 16 restricted-delivery source qualification

The isolated personal-computer branch prepares exact SPA routing, real unknown
route/asset 404s, explicit restricted robots/noindex policy and a text sitemap
404. All prior API, rate, identity, export, stream and hashed-asset configuration
bytes remain unchanged. The accompanying opt-in public checker uses seven fixed
unauthenticated paths, no credentials and bounded requests/bytes/deadlines.

Local qualification passed 20 offline guards and four network-none nginx
exercises: 29 delivery requests across all 14 routes, the retained 120-request
proxy exercise, 64 identity requests and 23 export requests. Every owned
container was removed and absence confirmed. Source/secret, lock, formatting
and lint checks passed. See [the implementation and limits](P13_PUBLIC_DELIVERY_CHECK.md).
Exact-head PR and distinct merged-main CI remain required. These are source
results; production still has the earlier discovery/404 gaps and schema8.
No CSP/HSTS, Google audience, grants or production configuration changed.

## Prepared workspace improvements

The navigation slice adds an accessible quick switcher for loaded titles,
drafts and existing actions, plus explicit search/loading/error states. It adds
no permissions, persistent index, provider traffic or automatic submission.
The retained 600 frontend tests, eleven workspace and three artifact-budget
regressions pass together (614 total). Both Opal and Legacy production builds pass the existing bundle
guard. The locked frontend audit reports zero known vulnerabilities. Earlier
synthetic browser review covered keyboard navigation, focus, mobile layout,
draft retention and unsaved-preference protection; see
[the implementation record](WORKSPACE_IMPROVEMENTS.md).

The integrated browser caught a 601,319-byte initial script against its unchanged
600,000-byte ceiling. Keeping the switcher index and demo history out of initial
delivery now yields 591,684/591,686 JS bytes (Opal/Legacy). The separate 80,000-byte
CSS cap caught an 80,495-byte initial stylesheet; moving dialog-only styles on
demand reduced both shells to 79,295 CSS bytes. The offline guard now checks both
unchanged limits before long browser journeys. A local recovery boundary
also contained a real 503 optional-shortcut download in the synthetic demo,
retaining unsent text and the workspace; the owned test server was stopped.

PR60 head `607f969` and distinct merged-main `96b6b10` each passed all nine CI
jobs (runs `43497121465` and `43500790670`), including authenticated disposable
database journeys. These results do not establish a deployed artifact or
public-user acceptance. The subsequent [mobile session repair](MOBILE_SESSION_PROGRESS.md)
adds separate browser-engine checks and records the targeted live HTTPS fix.

## Read-only public delivery observations

Five unauthenticated GET requests and the homepage were checked on November 13:

| Check | Observation |
| --- | --- |
| HTTPS homepage | HTTP200, HTML |
| `/api/ready` | HTTP404, JSON; private readiness is not exposed |
| `/api/v1/me` | HTTP401, JSON without a session |
| Existing response headers | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin` |
| CSP and HSTS response headers | Absent in this response; source nginx also has no such headers |
| `/robots.txt`, `/sitemap.xml` | HTTP200 HTML app shell, not actual discovery documents |
| Unknown route | HTTP200 HTML app shell |

These are observations of the unchanged production release, not a penetration
test or proof of the whole ingress trust chain. Browser-enforced CSP needs
Google sign-in, Plotly and both UI shells exercised against the real policy;
HSTS needs confirmed HTTPS/subdomain ownership and TLS termination. Do not
copy an untested policy into a production proxy or mark these gaps resolved.

## Remaining release gates

1. Complete P11 deletion recovery/retention and the fresh stopped-writer backup
   on the personal computer, following the [release handoff](PERSONAL_COMPUTER_RELEASE_HANDOFF.md).
   Requalify the exact combined image and source, not an earlier P11-only image.
2. Finish P12 mixed HTTP/provider/stream measurements, bounded synthetic model
   evaluation, agreed limits and SLOs. Component timings do not prove model
   accuracy or peak concurrent-user capacity.
   The 10,000-chat owner fixture exceeds the unchanged policy of 100 active
   chats/account, 1,000 total/account and 10,000 service-wide. It is a deliberate
   stress fixture, not a higher quota or a representative mixed HTTP workload.
3. Qualify the actual TLS/tunnel/proxy chain, response policy, rate-limit trust,
   private database reachability, secure-cookie/CSRF behavior and safe logs.
   Preserve the application database's network isolation and analytical grants.
4. Finish restricted-rollout discovery policy (robots/noindex/sitemap), public
   metadata/icons/social asset, real 404 behavior and link/accessibility review.
   Confirm policy/contact and retention language against actual operator practice.
5. Require all exact-head PR checks, distinct merged-main checks, source/image
   manifests, a schema 10-compatible fallback, rehearsed migration from the
   observed schema through the schema 9 authority boundary to schema 10, and independent
   backup restore. Confirm mail singleton locking, cleanup and readiness.
6. Perform the operator release review before any public audience/registration
   change. Restricted users receive no private dataset grant by default.
7. Record the release operator and incident contact, who monitors readiness and
   delivery after rollout, the rollback decision criteria and the selected
   compatible fallback. The service owner confirms the published support contact
   and retention information against operating practice.

No backup key, private environment, Google audience, database grant or running
application was changed by these preparations. The subsequent mobile repair
enabled only Cloudflare's HTTP-to-HTTPS redirect as recorded separately.
