# P10 progress

P10b security is deployed from PR55/main `7477e28` on private schema 6.
The release passed 1,519 backend cases, 492 frontend units, all 22 browser gates,
root review of 62 screenshots, and all three jobs on both PR and merged-main CI.
Stopped-writer state, configuration, database volumes and the mail schedule were
preserved. Public sign-in smoke passed without an authenticated account or
provider/model request. The exact release record is
`evidence/p10b/release.json`.

The P10B/P10C implementation documents capture their original isolated backend
contract snapshots. This progress record and the handoff's live checkpoint
describe current release status without rewriting historical test receipts.

P10c identity is deployed from PR56/main `d242d2e` on private schema 7 at
2026-10-31T04:08:14.829973+00:00. Its isolated candidate passed all 21
canonical checks and 1,635 backend cases, retaining every previous security
case. Its 528 frontend units and all 42 browser gates pass in both visual
themes; root inspected all 104 selected screenshots and full-resolution
identity details. The schema-7-compatible recovery image passes 1,530 cases,
retaining all 1,519 security cases, all 24 recovery browser gates and both
bounded frontend proxy checks. The current migration rehearsal preserves all
29 existing tables and created only the two expected empty tables. Both PR/main
CI passed all five jobs and 124 steps; fresh encrypted backup after writers
stopped and protected 30-day retention passed. Migration 0007 preserved protected
rows, volumes, environment and scheduler. Public GET-only sign-in smoke passed,
with its screenshot reviewed. P10 is complete. Exact release evidence is in
`evidence/p10c/release.json`; current browser/backend evidence remains in
`evidence/p10c/verification.json`. Failed attempts remain retained. Two initial
hosted matrix jobs reached the unchanged 120-second harness deadline; unchanged
retries passed, and the unproven timing cause remains a performance follow-up.

P11 is active. P11a exports are isolated implementation and verification.
Exports are not enabled in production.
P11 deletion, P12 capacity evidence and P13 launch gates remain incomplete.
