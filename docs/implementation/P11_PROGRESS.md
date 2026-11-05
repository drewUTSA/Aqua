# P11 progress

P10 is deployed and verified on schema 7 from PR56/main `d242d2e`.
P11 is the active phase; its privacy features are not deployed or enabled.

P11a personal exports passed all 25 isolated backend gates and 1,680 cases,
retaining all 1,635 identity/security cases. Both datasets passed restore and
bounded capacity checks. The current frontend passes 564 units over 279 inputs;
all 58 fresh browser gates passed across both themes. Root reviewed all 200
selected screenshots and eight full-resolution export details. A separate
two-theme unlink supplement passed and its four actual confirmation images were
reviewed, closing an inherited screenshot-label coverage gap without changing
the original evidence. The schema-8-compatible C fallback passed all 23 isolated
gates and 1,651 cases, retaining all 1,635 prior cases; both same-capped datasets,
restores and the 35-table clone/startup preservation passed. Fallback browser
compatibility, release helpers, PR/main CI and the gated release remain required.
Failed fixture/capacity/preload attempts
are retained and cannot satisfy current gates.

P11b/c deletion remains private implementation. Its independent retirement
authority requires a protected signed acceptance header before any accepted
response, immutable intent replay, complete fingerprint manifests before purge,
generation fencing and bounded physical cleanup. The current private authority
passed 61 native checks and an actual isolated PostgreSQL rehearsal, including
deferred COMMIT failure and an application-only restore that left the independent
retirement store unchanged. Host append-only durability, integrated deletion
routes, physical cleanup and their full security/recovery gates remain incomplete.

Backup retention remains 30 days with automatic pruning disabled; existing
backups have not been deleted. Recovery targets remain 24-hour RPO/four-hour
restoration targets, not guarantees. P12 measurements and P13 launch gates remain
incomplete; public audience expansion is not authorized by these preparations.

## November 5 implementation resumption

The prepared exports branch and the retained server-side deletion prototype
were recovered. Fresh read-only inspection corroborated the recorded P10c
images, schema 7, private database topology and mail schedule; the October 31
backup and public-smoke receipts remain historical evidence.

The current exports source passes all 1,680 backend case identities across both
isolated datasets, including both restore and bounded-capacity checks, and all
564 frontend units. Every prior 1,635 backend case and 528 frontend test
occurrence is retained and passes. Both frontend builds and bundle checks pass.
These results do not close the remaining fallback-browser, operator, CI or
production-release gates.

The first fresh backend run exhausted its unchanged 512 MiB temporary database
because repeated schema migrations accumulated dead system-catalog tuples.
The isolated core and capacity fixtures now run autovacuum every second; their
CPU, memory, storage, timeout and application assertions are unchanged. The
fixture guard also asserts the new maintenance cadence. The original
failure and the complete passing retest are retained separately. This setting
does not change the production database.

Deletion integration is proceeding on a separate branch. The recovered protocol
passes its 80 original checks in an isolated Linux container; application
integration, host durability, purge and recovery gates remain open.

The hosted export PR's backend job exceeded its 120-second complete-suite
deadline twice. The prepared runner repair collects the whole default suite and
executes four fixed, sequential module batches per dataset, each with a fresh
same-capped fixture and the original 120-second execution limit. Exact collection
and disjoint JUnit identities are required before the unchanged coverage and
capacity gates. Six new orchestration regressions and all 17 existing export
fixture guards pass locally; full hosted validation of this repair is pending.
The failed hosted runs remain evidence and do not satisfy the CI gate.
