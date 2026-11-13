# P13 launch preparation — November 13, 2026

**Decision: NO-GO for production cutover or public expansion.** Ben moved the
recovery-key discovery, backup/recovery and release execution to his personal
computer. The application remains on its healthy P11a/schema8 release. Code,
merged status, deployment and enablement are separate claims.

## Prepared workspace improvements

The navigation slice adds an accessible quick switcher for loaded titles,
drafts and existing actions, plus explicit search/loading/error states. It adds
no permissions, persistent index, provider traffic or automatic submission.
The retained 600 frontend tests and eleven added regressions pass together
(611 total). Both Opal and Legacy production builds pass the existing bundle
guard. The locked frontend audit reports zero known vulnerabilities. Earlier
synthetic browser review covered keyboard navigation, focus, mobile layout,
draft retention and unsaved-preference protection; see
[the implementation record](WORKSPACE_IMPROVEMENTS.md).

The complete final PR/main browser matrix, including authenticated disposable
database journeys, remains required. The local unit/build results do not
establish a deployed artifact or public-user acceptance.

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

No backup key, private environment, Google audience, database grant, running
application or production configuration was changed by these preparations.
