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

P10c identity is not deployed. The current isolated candidate passes all 21
canonical checks and 1,635 backend cases, retaining every previous security
case. Its 528 frontend units and all 42 browser gates pass in both visual
themes; root inspected all 104 selected screenshots and full-resolution
identity details. The schema-7-compatible recovery image passes 1,530 cases,
retaining all 1,519 security cases, all 24 recovery browser gates and both
bounded frontend proxy checks. The current migration rehearsal preserves all
29 existing tables and creates only the two expected empty tables. PR/main CI,
exact release images and the fresh encrypted backup after writers stop remain
required. No production schema-7 migration has occurred. Current browser and
backend evidence is in `evidence/p10c/verification.json`; prior failed attempts
remain disclosed and cannot satisfy current gates.

P11a exports are preparation in a separate workspace. Exports are not enabled.
P11 deletion, P12 capacity evidence and P13 launch gates remain incomplete.
