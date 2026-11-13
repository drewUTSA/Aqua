# P13 launch preparation — November 13, 2026

**Decision: NO-GO for production cutover or public expansion.** Ben moved the
recovery-key discovery, backup/recovery and release execution to his personal
computer. The application remains on its healthy P11a/schema8 release. Code,
merged status, deployment and enablement are separate claims.

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
   manifests, schema9-compatible fallback, migration rehearsal and independent
   backup restore. Confirm mail singleton locking, cleanup and readiness.
6. Perform the operator release review before any public audience/registration
   change. Restricted users receive no private dataset grant by default.

No backup key, private environment, Google audience, database grant or running
application was changed by these preparations. The subsequent mobile repair
enabled only Cloudflare's HTTP-to-HTTPS redirect as recorded separately.
