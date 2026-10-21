# P01 data boundaries and ingress policy

Base: merged PR #36, `271aa90a3d2a4175be4311f2d9ffcc230fad233d`.
This records implemented source controls, their isolated verification, and the
remaining deployment gates. It is not a production penetration-test certificate.

## Dataset and provider boundary

The application still uses its existing single analytical connection and explicit
account allowlists. P01 does not create the private application database or touch
the hosted database, its bootstrap scripts, `nl2sql/db.py`, or `nl2sql/config.py`.

Catalog loading recognizes exactly one reviewed dataset manifest: the eight
bank tables or the fifteen Pagila tables in `metadata_policy.py`. It considers
only ordinary/partition-parent tables in `public` that the current reader can
access. Other schemas, partition children, extra public tables, hidden staff
columns and ungranted columns are omitted. Missing/ambiguous supported manifests
fail closed. New customer datasets require a reviewed policy, not automatic
discovery or a frontend-supplied schema name.

There are three catalog queries and **no row-value sampling**. Provider-visible
comments, code dictionaries and enum/domain descriptions are versioned source
metadata. Existing bank annotations were reviewed from the repository's loading
script. Live table/column comments and category/person/district values are not
copied into prompts or embedding descriptions. Identifier/type/key metadata is
still visible for the authorized tables. This is an intentional provider data
contract, not a claim that all company schema metadata is public.

The question, approved schema, up to three verified training examples, answer-size
hint, and one previous model SQL plus a fixed repair diagnostic can reach the
configured provider/fallback chain. Actual query result rows, database exception
messages, connection strings, secrets, account/session records and raw provider
HTTP bodies are excluded. Questions can themselves contain user-supplied data;
future customer/provider consent controls remain P11. No real provider was called
by these tests.

Retrieval is an optimization inside the already authorized manifest. Its schema
text is discarded and regenerated from the trusted Schema. Declared and actual
example SQL relations must be allowed. Only explicit availability failures permit
fallback to the same authorized full schema. Authorization, integrity and unknown
failures stop before SQL generation. Existing stored schema-document text is not
sent at query time: retrieval selects table names and rebuilds the prompt.

## SQL and diagnostics

Physical relations are resolved with lexical CTE scopes and PostgreSQL identifier
rules. A CTE in an unrelated branch cannot exempt a real table. Catalog/database
qualifiers and non-public schemas are rejected; approved physical tables are
qualified as `public`. Unqualified functions resolve only in PostgreSQL's catalog
with transaction-local `search_path = pg_catalog` during execution, avoiding
public-schema overloads of approved names. The connection module and
server role settings are unchanged.

The existing forbidden-operation/function rules and hidden-column checks remain.
An additional allowlist rejects unreviewed analytical functions and qualified
user-defined functions. Quoted function spellings that the parser canonicalizes
are rejected rather than silently changing meaning. Queries are bounded to
32,768 characters and 4,096 visited AST nodes. Database grants, read-only
transactions, result row caps and statement timeouts remain separate controls.
The function allowlist can be expanded only with semantic/security review and
paired tests; it is deliberately not a general-purpose PostgreSQL execution API.

SQLSTATE chooses a fixed diagnostic and retry decision. Privilege failures,
timeouts and unknown failures are not repaired; eligible syntax/column/type
errors get at most one repair. Client contract codes remain `rejected` and
`query_failed`. Neither clients nor repair prompts receive raw database text.
Provider HTTP bodies and stop text are excluded from diagnostic messages.
Query-boundary logs contain categories/actions/attempt numbers only; parser
fallback warnings have zero SQL excerpt context. HTTP response keys are unchanged.

## Cache and algorithm costs

The query API checks current session and dataset permission before any cache
lookup. Keys retain exact question text and use structured typed encoding plus
SHA-256; case, embedded whitespace, punctuation and separator characters cannot
merge different questions. Server-owned namespace fields include verified Google
subject, dataset fingerprint, allowlist revision, schema revision, policy version,
standalone-context version, and relevant provider/fallback options. No cache key
or scope field is accepted from the frontend. P03/P07 will replace legacy
identities/revisions with canonical accounts and durable grant/chat revisions.

The LRU uses a lock and average O(1) lookup/eviction. Key hashing is O(question +
scope/config/schema bytes), not a claim of O(1) for arbitrary input. Cache size is
bounded to 256 entries, 1 MiB encoded content per entry and 16 MiB total encoded
content; Python object overhead is additional. TTL expires at the exact boundary.
Expired entries are removed on lookup and normal LRU eviction bounds untouched
ones. Failures are never cached. Cache entries are scoped to users, and access is
rechecked even if an entry exists. No persistent chat context exists yet.

Catalog assembly is O(tables + columns + constraints), with three round trips
independent of the number of text columns. SQL scope analysis is bounded by the
query limits and uses hash-set membership for relation/function policy. Database
join/filter plans remain PostgreSQL's responsibility; reference aggregate/CTE
queries compare the original and validated results on synthetic data. No claim is
made that every database operation can or should be O(n).

## Ingress and rate limits

Initial inspection found nginx on `0.0.0.0:5173` and the API tunnel going
directly to `localhost:8000`. The user authorized fixing this before commit.
The October 20 ingress-only hotfix now binds nginx to `127.0.0.1:5173`; the
backend remains on `127.0.0.1:8000`. Both public hostnames route through nginx.
The frontend container was recreated with the same static assets plus corrected
configuration; the backend container/image was unchanged. The operator ran the
root-owned tunnel update, and the agent independently verified its hash, active
process and public behavior. See [P01 ingress](../implementation/P01_INGRESS.md).

The installed nginx configuration listens on loopback and keys limits on the
socket peer. It never trusts `CF-Connecting-IP`, `X-Forwarded-For`, `Forwarded` or
cookies to create budget identities. Behind the current local tunnel, this is
deliberately a **shared aggregate budget**: query 10/minute + burst 5; Google
verification 5/minute + burst 3. Paths and trailing-slash variants share the
appropriate zone, with a conservative 12-second Retry-After and no-store 429.
Logout and health are not charged against the expensive-operation buckets.
Nginx's shared-memory accounting spans its workers; it is not durable across a
full restart and is not the later account/global limiter.

The two-worker isolated exercise proves forged-header/cookie churn does not
refresh the budget, route variants do not bypass it, rejected calls do not reach
the fake upstream, auth/query budgets are separate, oversized bodies are refused,
logout/health remain available, a bounded concurrent wave is accounted for, and
ordinary requests recover after cooldown. It tests nginx plus a synthetic
upstream, not Google login correctness or production throughput.

**Ingress gate resolved October 20:** both public hostnames now enter the
installed enforcement path at `http://127.0.0.1:5173`. Each returned healthy
no-store API responses and rejected a 17,000-byte request with nginx's 413 limit.
The exact live base image passed the same isolated 31-request limiter exercise;
no public rate flood or provider call was performed. Full P01 backend changes
are still local/uncommitted. Later releases must preserve this routing and verify
their exact configuration/images; do not enable public signup before durable
identity, admission and other applicable release gates pass.
Per-visitor real-IP parsing requires a verified exclusive trusted hop (for example
a dedicated socket/network ingress) and Cloudflare header overwrite behavior;
never trust all addresses or arbitrary loopback callers as distinct public users.

## Durable throttling design for the following phases

P02 supplies private storage; P03/P04/P07 implement server-side admission before
Google verification, password hashing, email enqueue, analysis and provider work.
Use a reviewed atomic token-bucket operation per policy dimension: canonical
account/operation, anonymous trusted network/operation, and aggregate expensive
work. Key anonymous identifiers with a server HMAC and bound TTL/cardinality.
Use database time and one transaction for reservation, not read-then-write races
or process-local dictionaries pretending to be multi-worker limits. Add fixed
global concurrency ceilings so random identities cannot allocate unlimited rows.
Release concurrency reservations exactly once; request and cost budgets are not
refunded just because an expensive provider attempt failed.

Store outage must reject costly work safely, with bounded timeouts; preserve
logout/revocation capacity. Uniform recovery responses must not expose account
existence. Test threshold/refill edges with a fake clock, concurrent workers,
restart/store failures, alternate routes, identity churn, key cardinality, provider
and email counters, fairness and recovery. P07 adds total deadlines, queue and
stream bounds; P12 measures capacity. These are future gates, not completed P01
features. Use `AQUA_CODEX_HANDOFF.md` for the full phase sequence.

## References

- [PostgreSQL SQLSTATE codes](https://www.postgresql.org/docs/17/errcodes-appendix.html)
- [nginx trusted real-IP configuration](https://nginx.org/en/docs/http/ngx_http_realip_module.html)
- [nginx request limiting](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html)
- [OWASP error handling](https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html)
