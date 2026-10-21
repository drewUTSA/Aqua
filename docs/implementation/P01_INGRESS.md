# P01 live ingress correction — October 20, 2026

**Resolved and independently verified.** The user requested fixing the direct
API tunnel bypass before commit. Both `aqua-ai.us` and `api.aqua-ai.us` now route
to `http://127.0.0.1:5173`, where nginx applies the corrected peer budgets and
request-size limit before the loopback backend at `127.0.0.1:8000`.

The broader P01 backend changes remain local/uncommitted and are not deployed.
This correction creates no application DB and implements no durable sessions.
See [the architecture and session requirements](../security/TARGET_ARCHITECTURE.md).

## Observed changes and verification

- Corrected nginx configuration SHA-256:
  `70abb93b69c4a9a333e1ce80627663a51d786da66c39338a32b63db4bfc59884`.
- Exact preexisting frontend base image
  `sha256:bd63990b7efe68cb1f2f8f2c9f5c3797def41b84a6f78a9078c0e413a0a0f08d`
  passed the same isolated two-worker, 31-request prevention/recovery exercise.
  Header/cookie churn, aliases, concurrency and cooldown passed; cleanup confirmed.
- A derivative image adds only nginx configuration, retaining existing assets:
  `sha256:a3b6f4886181904a095d18c2bcd6e6e77c5cfa305b51b88fdec7054e8f2b8c42`.
  Build used no network; nginx syntax/local health and runtime config hash passed.
  The frontend was recreated, and is healthy. Both app listeners are loopback.
- Backend container `0b698b7cad70` and image
  `sha256:110881615c3d042f3a852a9bc2ccf1b59f85ae68249a10b6d421532023532a17`
  remain unchanged and healthy. No analytical data, account data or credentials
  were accessed/modified by this operation.
- `/etc/cloudflared/config.yml` was root-owned. The account's noninteractive
  permission checks failed. A tested helper was staged in an owner-only AQUA
  home folder; the user authenticated and ran it with sudo. No new sudo grant,
  authorized key or account was installed. The helper validates the exact prior
  hash/routes and candidate rules, preserves an owner-only rollback copy, atomically
  changes only the two origins and restarts only `cloudflared.service`.
- The user's applied result was independently checked: installed config SHA-256
  `7b6b05537424aed6939df2b9bb086e5cd004c4d08b0734dc3e7b2eecd18e99d9`,
  root ownership retained, service active with PID `2756622`, and both origins
  point to nginx. Catch-all `http_status:404` is retained.
- Four public smoke requests at 2026-10-21 01:16 UTC (October 20 Chicago):
  each hostname returned 200/`status: ok`/`Cache-Control: no-store` for health,
  and 413 for a 17,000-byte POST to an intentionally nonexistent API route.
  Redirects were disabled, TLS checked, all resolved addresses were global,
  timeout six seconds/request, fewer than two requests/second. No login/query,
  provider, email or database operation was invoked. This was not a public load test.

Evidence: [evidence/p01/ingress](evidence/p01/ingress), including before/after
metadata, exact-image proxy exercise, gateway image/config report, public smoke,
operator provenance and helper hash. Three offline helper tests additionally
cover exact replacements and refusal of changed hashes, hosts, paths, catch-all
and duplicate routes. Helpers remain in the planning workspace for inspection.

## Source reconciliation before the next pull

Server Git HEAD remains the merged P00 base
`271aa90a3d2a4175be4311f2d9ffcc230fad233d`. The only intentional tracked server
change is `frontend/nginx.conf`, with the exact tested hash above, matching the
local P01 source. It is retained so an ordinary rebuild cannot restore the
vulnerable configuration. Existing untracked `.env.bak` remains untouched.

After the human reviews/commits/pushes/merges P01, inspect server Git status
again. Preserve this exact patch before a pull if Git requires it, verify the
incoming committed file has the identical SHA-256, and remove only the verified
duplicate local patch. Stop if either hash or unrelated work differs. Never use
a broad reset/clean or touch `.env.bak`. The next full build must use the merged
P01 source; this image-only gateway correction does not deploy backend fixes.

## Rollback and remaining gates

The old frontend image is retained as `aqua-ingress-before:p01`. The original
tunnel config is saved root-only at
`/etc/cloudflared/config.yml.aqua-p01-fa517093359c53be.bak`. Restore either only
under an explicit recovery decision: the earlier combination reopens a known
bypass. The helper rolls back the prior config if restart fails. No prune, data
rollback or backend restart is required by this hotfix.

The peer quota is a shared aggregate behind the local tunnel. Trusted visitor-IP
propagation, durable per-account/operation/global quotas, session issuance caps,
revocation, fair queues and capacity tests remain required in their phases.
Public signup remains gated. Application security is not complete merely because
these ingress checks passed; the recorded P01 failures and this bypass are fixed
within their tested scopes, and remaining controls are explicitly tracked.
