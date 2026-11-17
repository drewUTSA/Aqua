# P13 bounded public delivery inspection

> **Latest session: stopped November 17 UTC.** Read the [complete next-chat handoff](PERSONAL_COMPUTER_RESUME_20261117.md).
> Production remains on schema 8; the current operator is unfinished. Earlier sections retain their historical scope.

This source adds an opt-in diagnostic for the remaining P13 delivery work. It
is separate from the restricted delivery source fixes described below. It
does not change a running service. **A successful inspection does not close P13 or
authorize a production cutover/public launch.**

## Restricted delivery source fixes

The accompanying nginx source serves the app shell only for the exact 14
current frontend `LOCAL_PATHS`, including auth and account-action pages. Query
strings still reach the same route and the frontend retains its existing
in-memory proof/consume-and-clear behavior. Existing static files remain
available; missing assets and unknown routes return HTTP404 instead of an
HTTP200 app shell. The maps and all prior API, denial, rate, export, stream,
security and hashed-asset locations are unchanged.

For the current restricted launch, `/robots.txt` returns text/plain with
`User-agent: *` and `Disallow: /`; `/sitemap.xml` intentionally returns a
text/plain HTTP404. The HTML includes `noindex, nofollow`. These crawler hints
are not access controls. A later public launch must explicitly review/change
discovery policy. CSP and HSTS are unchanged pending real ingress/browser
qualification; no Google audience, dataset grant, backend policy or visual
design changes are included. These source edits are not a deployment.

## Safe default and explicit execution

From the source checkout, print the fixed inspection plan without networking:

```text
python tools/checks/check_public_delivery.py
```

After source review, explicitly request live unauthenticated GETs:

```text
python tools/checks/check_public_delivery.py --execute
```

The only alternate origin is `--origin https://www.aqua-ai.us`. Origins are
fixed CLI choices; no arbitrary URL, request header, token, cookie, credential,
environment-file or proxy option exists. The HTTPS transport uses no cookie
jar or netrc. The disposable network worker inherits only `SystemRoot` on
Windows, required by WinSock DNS; it defaults to `C:/Windows` if absent. On other
platforms its environment is empty. No PATH, proxies, provider keys, credential
variables or certificate overrides are inherited.
Both origins are inspected separately, never as an automatic cross-origin hop.

An optional `--output NEW_RECEIPT.json` writes a create-only sanitized receipt.
Its parent directory must already exist. Existing files/symlinks are refused
before network execution. Without `--output`, only sanitized JSON is printed.
No output directories or response-body files are created.

## Closed request and resource scope

Seven fixed paths are planned: `/`, `/signin`, `/robots.txt`, `/sitemap.xml`,
`/_aqua_public_delivery_missing_20261116`, `/api/ready`, and `/api/v1/me`.
The last two are public unauthenticated denial checks, not authenticated calls.
There is no analytical question, provider invocation, sign-in, write, load
test, crawler or arbitrary endpoint discovery.

The checker allows at most eight GET requests total: seven probes and at most
one extra redirect request when the budget permits. A redirect is followed only
within the exact selected HTTPS origin and only to another fixed path. A
query, fragment, userinfo, explicit port, off-origin destination, loop or longer
chain is rejected. Redirect bodies are not read or stored. A rejected redirect
or exhausted budget makes the inspection incomplete, rather than claiming the
destination was verified.

Each response body is capped at 65,536 bytes, with an 8,192-byte maximum read
chunk and a one-byte overflow detector. Non-identity content encoding and
invalid/mismatched Content-Length are rejected; no decompression is performed.
Connect/header timeout is three seconds, each body read has at most two
seconds, and the complete live invocation has a hard 20-second child-process
deadline. That outer process bound also covers a stalled DNS resolver or TLS
setup. A terminated worker reports an unknown request count, never zero.

## Reading the receipt honestly

The receipt reports initial/final status codes, byte counts, completion/error categories and
header classifications. CSP and report-only CSP are separate booleans. HSTS
presence and a positive parsed max-age are separate; neither proves a correct
browser policy. Frame/nosniff/referrer-policy findings are limited observations.
No HTML, JSON response content, raw header values, cookies, redirects, prompts,
credentials or untrusted exception text is copied into the receipt.

Discovery checks classify MIME types, detect an HTML document prefix and look
for bounded robots/sitemap markers. They do not fully validate robots policy,
XML syntax, sitemap URLs, crawler access, metadata, icons or social previews.
The missing-route check reports whether that fixed path initially returns HTTP
404; a redirect ending in 404 does not count. An HTTP200 SPA shell is reported
as such. Readiness hidden by 404 and
profile denied by 401/403 are distinct from general application/provider health.
Incomplete probes produce null aggregate observations instead of false passes.

Exit zero means all seven bounded observations completed (or the CLI printed
the plan). It does not mean CSP/HSTS/discovery/404 requirements passed. Exit one
means inspection was incomplete; argument/output-preflight errors use argparse's
normal nonzero result. `p13_launch_complete` is always false.

P13 still requires review of the actual TLS/tunnel/proxy chain and rate-limit
trust, policy qualification across Google sign-in/Plotly/both UI shells,
secure-cookie/CSRF behavior, restricted discovery policy and truthful contact/
retention statements, exact release/recovery evidence and operator review.
Keep production policy changes in their own reviewed change.

## Offline verification

```text
python tools/checks/test_public_delivery.py
python tools/checks/test_public_delivery_routes.py
python tools/checks/run_public_delivery_proxy.py --output NEW_FIXTURE_RECEIPT.json
```

Fake transports and clocks test fixed GETs, rejection of POST/auth headers and
other origins, no cookie reuse or response/header/exception leakage, redirect
bounds, byte/encoding/length limits, connect/read/total deadlines, private-route
denials, SPA discovery behavior and create-only/no-network defaults. The outer
process contract is mocked. Tests perform no real network requests.

The separate nginx fixture uses only owned, disposable containers: nginx with
network none, and a synthetic client sharing that namespace. It publishes no
host port, mounts no host directory and copies only source/config/synthetic
files through stdin. Its GET-only exercise has 48-request/20-second/body bounds
and checks every allowed route, query variants, unknown/missing routes and
assets, static files, exact robots/sitemap responses and private readiness
denial. Containers are removed and absence is checked. Existing ordinary,
identity-action and personal-export proxy exercises remain required, unchanged.

No live execution is claimed by this document. A future live receipt is a
point-in-time public delivery observation, not a penetration test or launch
certificate. See `P13_PROGRESS.md` for the controlling remaining gates.
