# Approved target architecture and session-abuse boundary

October 20, 2026. The user's architecture sketch is the target direction.
This records the necessary trust boundaries; it does not mark future phases done.

```mermaid
flowchart LR
    U[User browser / React] -->|HTTPS| C[Cloudflare edge + tunnel]
    C --> N[nginx gateway / static assets]
    N -->|Restricted API routes| B[Backend API / authorization / admission]
    B -->|Application runtime role| A[(Private application PostgreSQL)]
    B -->|Read-only analytical role + TLS| D[(Hosted company dataset)]
    B -->|Authorized bounded context| M[Approved model / retrieval provider]
    B -->|Identity + policy-scoped results| K[Bounded private cache]
```

## Meaning of the boundaries

React executes on the user's device. Its code, requests and client state are
inspectable and cannot store secrets or enforce database permissions. The browser
calls an API exposed through the gateway. That API must authorize every operation
even when someone bypasses the UI or uses their own HTTP client. The Python
listener itself is loopback/private; public traffic must always enter nginx.

Only the backend connects to databases. Account/session/chat/preferences storage
is separate from analytical company data, with different credentials and grants.
No app DB port is published publicly; runtime cannot do migrations/DDL. The AI
analytical reader cannot access account/session records. Cloud location does not
make a database private: restrict its network clients, require verified encrypted
connections, and use least-privilege credentials and bounded queries. Changes to
the existing hosted database and connection modules remain outside P01 scope.

The database's security comes from authorization, network restrictions, grants,
safe query execution, credentials and monitoring, not from the number of boxes
between it and the browser. A backend compromise still matters; separate roles,
bounded worker access and recoverable backups reduce its reach. Multi-customer
dataset selection must be resolved from server-owned grants, never a browser DSN.

Cloudflare may cache public static assets. Authenticated API responses, sessions,
prompts, results and exports must not enter a public/CDN cache. The private result
cache stays behind authorization and is partitioned by canonical identity,
dataset/grant, policy/schema and conversation revision as those phases arrive.
Credentials and session tokens are never cache keys exposed to the client.

## Session ownership does not provide admission control by itself

The user explicitly requires that one person cannot acquire extra server capacity
by creating many sessions, and cannot read or mutate another person's session.
Treat this as a mandatory P03/P07 security gate before public signup.

Current P01 baseline: verified Google identity, signed expiring stateless cookies,
host-bound Secure/HttpOnly cookies, CSRF and dataset allowlists. Logout clears the
browser cookie but cannot revoke a copied cookie before expiry. There is no
durable account/session table, active-session ceiling or durable account quota
yet. P01's corrected gateway uses one socket-peer aggregate budget behind the
tunnel; forged headers and cookie churn do not create fresh budgets. It does not
claim per-user fairness or durable multi-worker quotas.

P03 must implement opaque unpredictable session tokens with only digests stored
server-side, canonical account ownership, absolute/idle expiry, rotation and
revocation. Never treat a browser-supplied account/session identifier as authority.
Lookups, listing and revoke-one operations must be owner-scoped. Logout must
revoke server state before clearing the cookie; reset, disablement and revoke-all
must invalidate copied cookies and existing streams. Reject the old stateless
format at cutover so it cannot bypass durable checks. A stolen bearer cookie is
still a credential: cookie protections, short bounds, detection and revocation
reduce risk; session records alone cannot prove the caller is the original device.

Add a small server-controlled active-session ceiling per canonical account.
Choose/document its numeric policy in P03; an atomic account lock/transaction must
prevent parallel logins from exceeding it. Reject excess issuance safely and
provide an authenticated session-management/revoke flow. Do not silently grant
fresh quotas per device or evict legitimate sessions based on unauthenticated
claims. Limit Google challenge/session creation by trusted network and global
budgets before provider calls; apply verified-account issuance limits afterward.
Do not key an unauthenticated quota on an attacker-supplied email address alone.

P03/P04/P07 admission must share account/operation budgets across all that
account's sessions, plus trusted anonymous-network budgets and global work/cost
ceilings. Bound the number of keys and their retention. Reserve work atomically
across workers, with bounded timeouts and safe behavior on storage failure.
Account caps alone do not protect against many accounts; network/global caps do
not replace account fairness. Start from the handoff's proposed two active costly
jobs per user and benchmark numeric global concurrency/queue/memory limits in
P12; enforce explicit limits before enabling the relevant capability.

## Required adversarial and defensive evidence

- A and B cannot substitute session IDs, list/revoke each other's sessions or
  receive each other's cached results. N has an account without a dataset grant.
- Parallel logins/challenge replay cannot exceed the session ceiling, duplicate
  identity records or mint multiple sessions from a single-use challenge.
- Cookie clearing, new devices, reconnects and parallel sessions do not refresh
  account/global budgets. Key cardinality remains bounded under random identities.
- Copied cookies fail after logout/reset/disable/revoke-all, including in-flight
  and replayed result streams; expiry/revocation races cannot publish private data.
- Rejected requests do not invoke a model, hash passwords, send mail, enqueue work
  or modify another user's state. Exercise store outage, worker restart and queue
  saturation using isolated fixtures and work counters; prove cooldown recovery.
- Legitimate B traffic retains intended capacity during A's abuse. Alerts/logs
  record category/action and bounded identifiers without cookies, tokens or data.

Use the same phase red/blue/fix/retest and CI process as P01, with exact scope and
budgets. A signed cookie, a request counter or a 429 alone is insufficient evidence.

## References

- [OWASP REST API security](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html)
- [OWASP database security](https://cheatsheetseries.owasp.org/cheatsheets/Database_Security_Cheat_Sheet.html)
- [Cloudflare ingress validation and routing](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)
