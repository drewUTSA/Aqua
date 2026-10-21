# P02 release — private application storage

October 20, 2026, Chicago. P02 PR [#38](https://github.com/drewUTSA/Aqua/pull/38)
is merged at `5ac90fcca45a6a74bab5d6f792388c05804d87a2`. The server checkout at
`/srv/bank-ai` was fast-forwarded to that commit and the reviewed images were
deployed. This supersedes the installation-pending status in the historical
[P02 implementation checkpoint](P02.md).

## Deployed state

| Component | Observed state |
| --- | --- |
| Backend | Healthy; `sha256:71ff1e332cca32e441bc4f6f4f1b2b44a25b73d4be5cc5c653697aba35e3d6f3` |
| Frontend/nginx | Healthy; `sha256:ac73aed548459eab3fb278926d46200311d829b0be6ebccd4da44deba79b2ed5` |
| Private DB | `aqua-app-db`, database `aqua_app`, schema version 1; repeat migration succeeds |
| Isolation | Docker network `none`, no TCP listener or published DB port; explicit Unix-socket attachment only |
| Storage activation | Private runtime configuration enabled; loopback readiness reports storage ready/schema 1 |
| Existing authentication | Google cookie flow unchanged by P02; durable-session cutover remains P03 |
| Git checkout | Only the pre-existing untracked `.env.bak`; its contents were not read or changed |

Separate data/socket volumes and private role credentials were installed using
the reviewed operator helpers. Runtime cannot perform DDL or alter the migration
ledger; a subsequent ordinary read succeeds after the expected denial. The
hosted analytical database, its bootstrap scripts and its connection module were
not changed. Neither password signup nor new dataset grants were activated.

## Release verification

The actual backend image passed both isolated fixtures: 742 bank tests and
749 Pagila tests, covering all **761 distinct tests** between them. Exact-image
packaging matched 38 reviewed files. The isolated installer, SCRAM authentication,
repeat migrations, restricted synthetic export and cleanup passed. Synthetic
dump/restore preserved rows and privileges and applied recovery session fencing.

The 35-request isolated nginx exercise passed containment and cooldown recovery.
Both public hosts then passed a six-request smoke check: liveness 200/no-store,
private readiness 404, and a 17,000-byte probe rejected with 413. Public checks
did not authenticate, query customer data, call a model or send email.

Evidence belongs in [evidence/p02-release](evidence/p02-release):
`p02-release-{sync,build,check,install,activate,verify,public}.json`, together with
the bounded isolated reports. Image IDs and observed results above come from
those release records.

These are scoped regression and release checks, not a complete production
penetration test or a capacity guarantee. The recovery result on the installed
service is recovery after a denied runtime operation; **no real encrypted
off-server application snapshot was restored**. Backup collection scheduling,
retention and measured RPO/RTO remain release work. Preserve both DB volumes and
private credentials; do not rerun bootstrap or remove data to undo a release.

P03 is prepared separately for canonical identity and revocable sessions. Its
schema-2 migration and deliberate legacy-cookie rejection need the
[P03 cutover procedure](../ops/P03_IDENTITY_CUTOVER.md).
