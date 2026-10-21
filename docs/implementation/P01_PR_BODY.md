Title: Enforce analytical data boundaries and test proxy admission

Generated queries could confuse qualified relations with allowed tables, cache
keys could merge different literal questions, and database/retrieval metadata
could cross the provider boundary. This change introduces explicit reviewed
dataset metadata, scoped cache keys, safe diagnostics and fail-closed retrieval,
with lexical SQL validation and catalog-only function resolution. It also fixes
forged-IP rate-limit identity and adds a bounded two-worker nginx regression to CI.

Validation: all 727 distinct backend tests pass across two isolated PostgreSQL
fixtures; 47 frontend tests, build, Black/Ruff, lock/source checks and dependency
audits pass. Red baseline findings, paired retests, 31-request limiter exercise,
hashes, budgets and cleanup are recorded in `docs/implementation/P01.md` and its
evidence directory. Existing analytical connection modules and `db/` are unchanged.

The user-authorized ingress-only hotfix is live: both public hostnames enter
nginx, its exact runtime base passed the limiter test and public health/body-size
checks passed. The backend remains on its prior image pending this PR. The peer
quota is aggregate behind the tunnel; durable account/session/global controls
remain later phases. Customer data, the account database and signup are unchanged.
