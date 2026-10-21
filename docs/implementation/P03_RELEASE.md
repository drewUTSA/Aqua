# P03 release — durable identity and sessions

October 20, 2026, Chicago. PR [#39](https://github.com/drewUTSA/Aqua/pull/39) is merged at `c25a3332e67f644e94c6ab3b6e80155dacf7c56b`. The `/srv/bank-ai` checkout and running services were synchronized to that release. This supersedes the deployment-pending status in the historical [P03 implementation checkpoint](P03.md).

| Component | Verified release state |
| --- | --- |
| Backend | Healthy; `sha256:b0bd8621bfaca1669d26c8e01b50edd5e9ccc4393918e70d88fedf7c83c68800` |
| Frontend/nginx | Healthy; `sha256:cafe40e786635bd833e228e7aaf81359e239413311dd6cd0d288aeac912b5fae` |
| Private app DB | Schema 2; repeat migration succeeds; internal readiness reports storage ready |
| Isolation | `aqua-app-db` remains network `none`, Unix socket only, without a TCP listener or published database port |
| Runtime permissions | DDL and migration-ledger writes are denied; normal reads recover after the expected denials |
| Authentication | Opaque durable sessions and deliberate rejection of legacy signed cookies; existing users reauthenticate |
| Unchanged scope | Hosted analytical database, Google audience/approvals and public signup settings |
| Server checkout | Preserved the pre-existing untracked `.env.bak`, without reading or using it |

Before cutover, an encrypted off-server snapshot was collected and its data integrity checked: snapshot `62737bad9e89c1e6c6836664ab5b725b2f01bd9a8b5b296b2b602fc837ee1f6c`, tag `pre-p03-c25a333`, schema 1. No plaintext dump was saved locally, and no pruning occurred. This is an actual collected backup, **not a successful production restore**. Independent password recovery, collection scheduling, retention and measured RPO/RTO remain operational requirements.

The exact release image passed all **835 distinct backend cases** across both synthetic datasets: bank 816 passed/19 dataset skips; Pagila 823 passed/12 dataset skips. Every case passed in at least one fixture. All 43 packaged runtime files matched source hashes. The 48-request isolated nginx abuse/recovery exercise and disposable installer/repeated migration/SCRAM/runtime-denial/export checks passed. Synthetic restore preserved rows and privileges and fenced restored sessions. Temporary exercise resources were removed and their absence confirmed.

A bounded ten-request public smoke passed through the real ingress: liveness, private readiness denial, no-store responses, secure bootstrap cookies, unauthenticated `/me`, oversized-body rejection and legacy-cookie rejection. It did not use a real Google credential, authenticate a customer, query business data, call a model or send email. Isolated adversarial checks are not a production penetration test or a capacity guarantee.

Release evidence: [evidence/p03-release](evidence/p03-release), including synchronization, image/build checks, the operator backup report, cutover and bounded public verification. The [identity cutover runbook](../ops/P03_IDENTITY_CUTOVER.md) remains historical procedure; the observed release state above is authoritative.

P04 starts from this deployed schema-2 release. Its schema-3 password/mail source requires a new review and explicit migration. Preserve both database volumes, private credentials, backup snapshots and immutable migration checksums. Do not rerun bootstrap, restore old authorization automatically or roll authentication back to stateless cookie acceptance.
