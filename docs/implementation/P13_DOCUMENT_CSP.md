# P13 document policy source slice — November 16, 2026

> **November 25 source update.** Both document locations now enforce the complete policy. The password and synthetic Google sign-in checks run on both layouts with the source headers. The November 16–17 design and acceptance notes below describe the earlier report-only rollout.

> The source also sends one year of HSTS with subdomains, an explicit device permissions policy, same-origin resource protection and popup-compatible opener isolation. Anonymous Google SDK loading and a cross-origin popup were checked in fresh local browser profiles. Before release, the owner must populate the reserved contact in `frontend/security.txt` and renew its expiry.

> **Historical session: stopped November 17 UTC.** Read the [complete next-chat handoff](PERSONAL_COMPUTER_RESUME_20261117.md).
> Production remains on schema 8; the current operator is unfinished. Earlier sections retain their historical scope.

This is source preparation, not deployment or live Google/TLS acceptance.
Production remains on its schema8 release. Deletion/recovery, analytical DNS,
capacity and public-rollout gates remain separate. No HSTS, COOP, COEP, new
audience, dataset grant, provider access or production configuration is enabled.

## Policy boundary

The two nginx SPA/fallback locations enforce only `object-src 'none'`,
`base-uri 'none'` and `frame-ancestors 'none'`. The fuller subresource policy is
report-only in source. It restricts scripts to same-origin and the exact Google
Identity Services client; inline handlers and evaluation are not authorized.
GIS frame/connect/style sources follow Google's documented endpoints.
Local/data images and local fonts are allowed. Plotly's pinned basic bundle
inserts style rules, so inline style remains an explicit compatibility exception.
No report endpoint or script sample is configured.

The protected nginx API/auth/rate/export/stream/asset prefix is unchanged.
Document policies are not added to API responses: the existing Google redirect
bridge retains its independent fresh-nonce CSP. Multiple enforced CSPs intersect;
a restrictive global proxy policy could otherwise block the bridge's script.
nginx1.27 location header inheritance requires retaining the existing explicit
cache, framing, nosniff and referrer headers in both document locations.

## Qualification contract

The test-only `csp-policy.mjs` projects and validates actual nginx policy bytes.
Both loopback and reserved-HTTPS static fixtures use that projection. The closed
boolean `cspEnforcedFixture` option substitutes the full candidate as an enforced
header only inside a browser fixture; no environment value changes source mode.
The existing P08 real-Plotly journey explicitly selects it for both UI shells.
All existing visual assertions, fake-provider boundaries and resource/request/
deadline ceilings remain. Other browser fixtures retain source policy mode.

A real same-origin script element loads the fixed, fixture-only canary script.
Its DOM insertions test inline scripts/handlers, evaluation, an altered base,
external image/frame/object and fetch. CSP must block those before external
transport; the independent browser interceptor still rejects every external
request if enforcement fails. The probe is served once and remains inside the
original request/deadline budgets. It is not bundled into application assets.

Browser diagnostics contain only bounded directive/disposition counts, the
policy hash and fixed completion flags. Application violations and deliberate
canary violations have separate buckets. No document/blocked/source URL,
credential, query, script sample or raw browser diagnostic is collected by the
CSP observer. Any unexpected application violation fails the P08 qualification.
Actual nginx checks verify document200/404 policy headers and the absence of a
competing document CSP on readiness and hashed assets.

The blocked base element stays inert until the fixture document is discarded.
Removing it caused Chromium to re-evaluate the base and emit a second deliberate
violation. A fixed minimal local document reproduced nine events before that
cleanup repair and exactly eight afterward, with the same policy hash, no
external transport and confirmed cleanup. Unexpected application events still
fail; no allowance, policy or budget was relaxed. The full Plotly journey remains
the combined application acceptance gate.

Root's local qualification passes eleven focused Node guards, three Python CSP
guards, both production builds and the actual network-none nginx fixture
(29 requests across14 routes,24 policy responses, exact cleanup). The current
full CI must also pass both-shell P08 browser enforcement and unchanged proxy,
export and identity gates before this slice is accepted.
Use the repository's existing pinned isolated runners; do not substitute a live
provider or production database. Suggested focused commands from repository root:

```text
node --test frontend/checks/csp-policy.test.mjs frontend/checks/csp-browser-probes.test.mjs frontend/checks/p10b-browser-mode.test.mjs
python -m unittest discover -s tools/checks -p test_csp_headers.py
python -m unittest discover -s tools/checks -p test_public_delivery_routes.py
```

Then use the retained frontend builds and P08 runner for `opal` and `legacy`,
plus `tools/checks/run_public_delivery_proxy.py` in its existing owned,
network-none fixture. Browser runtime inputs must bind this changed source.

## Remaining acceptance

P08 supplies a synthetic Google object before navigation. It does not load the
real GIS SDK, so even a passing full-policy fixture does not qualify real Google
popup, redirect, account reauthentication/linking or iPhone browser behavior.
Keep the source subresource policy report-only pending those explicit checks.
Do not self-host an offline GIS copy or weaken auth to simulate live acceptance.

HSTS belongs at the verified HTTPS termination boundary. This nginx listener is
HTTP behind the ingress, so `$scheme` does not establish public HTTPS and request
forwarding headers must not activate HSTS. After verified ownership, certificates/
renewal and redirects for apex/www, an operator may separately review a short
host-only max-age, then increase it after acceptance. `includeSubDomains` and
preload remain off until every affected name is independently qualified.

References: [Google GIS CSP setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid#content_security_policy),
[nginx header inheritance](https://nginx.org/en/docs/http/ngx_http_headers_module.html),
[CSP style attributes](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/style-src-attr),
[HSTS behavior](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Strict-Transport-Security).
