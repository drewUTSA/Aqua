# AQUA stop checkpoint — November 17, 2026 UTC

## Read this first in the next chat

Ben explicitly requested stopping release work and saving context for a different
chat tomorrow. This checkpoint supersedes older resume instructions about what
to do next. Do not resume automatically until Ben asks. The objective remains
finishing the guarded P11 schema9/private-deletion release, followed separately
by P12 capacity/retrieval and P13 hardening/restricted launch. P00–P10 are done.
Do not restart their matrices or treat an old planning kickoff as current work.

Use `/Users/bspear2004/Documents/ChatGPT/AQUA_FINAL`, remote
`https://github.com/drewUTSA/Aqua.git`. The stop/handoff branch is
`codex/aqua-stop-handoff-20261117`; inspect its actual HEAD and Git status first.
The last merged main at the stop is
`3fd413ccad9e40021ea06ea21b11dbdd930121d6`. A later handoff commit is a
documentation checkpoint, not a deployment or a newly passing release CI gate.

Read this file, `CLAUDE.md`, the root `AQUA_CODEX_HANDOFF.md`,
[the previous detailed continuation](PERSONAL_COMPUTER_RESUME_20261116.md), and
[the activation profile](P11BC_ACTIVATION_PROFILE.md). The main local evidence
and uncommitted operator work are under
`.check-results/resume-20261116/` in this checkout. That directory is ignored by
Git. **Keep this checkout and its ignored files**: a fresh clone contains the
curated receipt pins, not the full local source proposals, logs, CI artifacts or
native receipts. Older `/Users/bspear2004/Documents/Aqua` and
`/Users/bspear2004/Documents/Aqua-p11-deletion` also contain referenced historical
fixtures; preserve them. Nothing authorizes resetting or cleaning those trees.

The repository's Markdown context links point here. Two Markdown reference
files, `frontend/BACKEND_INTEGRATION.md` and
`frontend/checks/WORKSPACE_RELIABILITY_BROWSER.md`, are themselves among the
339 qualified frontend inputs and deliberately retain their exact bytes. Their
current session context is this handoff; editing them just to add a stop notice
would invalidate the saved source fingerprint. All other previously tracked
Markdown files received the current handoff link without replacing their history.

The prior `Frontend-Work` chat had stopped with 37 F1–F4 controls and returned PC
work to Mac ROOT. The subsequent Mac chat's unfinished objective was current
source/CI/runtime/profile closure followed by fresh app recovery, authority
retention and guarded schema9 activation. This chat reconstructed that context
from both chats and the handoffs. No new worker chat needs to be launched.

## Production and Git state at the stop

- Production remains healthy **schema8/P11a exports**, 36 app tables and all
  eight migration checksums. Deletion is inactive and retirement authority has
  not been installed. No production migration0009 or deletion activation ran.
- The server checkout `/srv/bank-ai` remains clean at
  `9aeaf4eb91a4db55d3701e8be872f2b1e178a116`; do not blindly pull and run
  `docker compose up`. Source, live configuration and keeper sequencing must
  follow the reviewed release operation.
- The earlier completed fresh app backup did stop and restart the same old
  backend. Do not claim that this entire session made no service actions. The
  subsequent qualifications were disposable and their scopes are recorded.
- The last independent scan found 16 containers and the full production
  reference unchanged. All ten HTTP test IDs and the later never-started
  metadata probe are independently absent. Candidate images and public source
  stages were intentionally retained. No native lane or cutover is running.
- PR73 merged the permanent publisher cleanup-reserve fix; PR74 merged the
  recovery/native evidence checkpoint. PR74 run `44008649139` and main run
  `44011379683` each passed all 15 jobs. PR API head `1d2e34b` and actual tested
  synthetic merge `ffad9b8` are distinct; final merged main is `3fd413c`.
  Future checkpoint/release PR and main CI must be verified on their own heads.

Production image identities:

| Service | Image |
| --- | --- |
| Backend | `sha256:dec35c031486fbb5a16cf823bd14073d704f507c94c1c1cbbaa71a6acd4b5962` |
| Frontend | `sha256:4fab90c0016ab600fc11e337766cee54b5ee22e4d2330f6829502bd28f41adcb` |
| PostgreSQL17 | `sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826` |

## Completed evidence — reuse the exact qualified components

The following completed components do not need replay merely because the
operator dossier is unfinished. Verify their files/pins and source predicates;
preserve each earlier red attempt and each original resource/deadline limit.

| Component | Exact local entry point / receipt |
| --- | --- |
| Backend source/lock/CI closure | `backend-closure-v1.ROOT_REVIEW.json`; `backend-closure-v1/closure-result.json` |
| Actual backend image inventory | `backend-inventory-v3/ROOT_FINAL_REVIEW.json` |
| Frontend browser/test-source closure | `frontend-browser-closure-v2.ROOT_REVIEW.json`; `frontend-browser-closure-v2/closure-result.json` |
| Native static images | `frontend-native-v3/ROOT_FINAL_REVIEW.json` |
| Real default HTTP and unchanged proxy/export checks | `frontend-http-native-v3/ROOT_FINAL_REVIEW.json` |
| Current-image migration and catalogue | `migration-current-v3/ROOT_FINAL_REVIEW.json`; `ROOT_CURRENT_CATALOGUE_WITNESS.json` in that directory |
| Actual 256 MiB metadata inspection | `metadata256-native/v4/ROOT_FINAL_REVIEW.json` |
| Full five-section activation/CAS/publisher QA | `activation-native/v1/ROOT_FINAL_REVIEW.json` |
| Installed publisher normal/cancel qualification | `publisher-native/v3/ROOT_FINAL_REVIEW.json` |
| Fresh schema8 app backup/restore | `schema8-backup/ROOT_PRODUCTION_BACKUP_FINAL_REVIEW.json`; `schema8-restore/ROOT_FRESH_RESTORE_FINAL_REVIEW.json` |
| Synthetic encrypted authority capture/readback | `authority-qa-v1/ROOT_FINAL_REVIEW.json` |
| Existing current-image ordinary startup/recovery | `normal-current-provenance/ROOT_FETCH_REVIEW.json`; `normal-original-stdout.json` |

All paths in that table are relative to `.check-results/resume-20261116/`.
The five committed `evidence/p11bc/current-*-20261117.json` anchors curate the
component hashes. Their `release_eligible:false` scope is intentional.

The qualified release backend is
`sha256:61034825653941c528a17bd66d3d0072c18b1a57d82377053d349d6204c7ef66`.
It has **207 compiled inputs = 198 Python + 9 SQL**, 210 app files and 211
including the lock. App files are actually UID/GID1000 mode0755; the lock is
root-owned mode0755. There are 49 locked distributions plus base pip25.0.1,
50 actually observed, with pip-check passing. Do not substitute historical
195-file/1851-case counts or tighten file modes on paper.

The complete backend bridge binds all 630 source files, the lock/package graph,
eight fresh CI fixture pairs/restores and 2121 core case identities per dataset;
2122 merged identities include the separately run capacity case. Original CI
enforced collection/JUnit identity equality. Raw JUnit was not re-read by this
bridge; it does not claim every case passed both datasets. Its CI dependency
image `826915…` is distinct from native release image `610348…`.

Both frontend shells have 339 source inputs, 680 unit cases and 19 built image
files (18 served plus `.vite/manifest.json`). Native images are:

- Opal: `sha256:49e4ab58bc7b502592106f5812cf213d0bca77255f354dd6bea6a76926af0e01`.
- Legacy: `sha256:6e2c98c29aea1da3beb9bed3d8d60493531ae15bbc64af78845ea0ce6013992d`.

The 959-file browser/source closure preserves 79 custom reports/1456 checks and
six Playwright reports/108 cases per run, with zero unexpected skips. Exactly
four Legacy skips correspond to intentional Opal-only steps. Both native images
passed actual default ENTRYPOINT/CMD startup, exact Compose wget command with
five-second timeout, nginx configuration/index hash and graceful exit, plus the
unchanged original 120-request proxy and 23-request export exercises. All ten
actual container IDs are independently absent. This is isolated HTTP proof;
full Compose host/default capabilities, scheduler, ingress/TLS and production
browser/deployment scope are not inferred. Earlier buildx/User-parser failures
remain recorded, including the V2 pre-create red.

Current migration QA preserved 35 populated old protected tables and added four
(39 protected tables). All original 16 migration checks, seven defaults and
negative drift/ACL/work-marker checks passed. The 149-row schema9 catalogue has
all nine ledger checksums. Its collector uses exactly one disclosed fixture
DSN-host substitution; it was not the canonical program executed unmodified.
The separate actual metadata profile is 256 MiB/1 CPU/32 PIDs/110 seconds and
passed seven probes/six assertions. The 1 GiB migration fixture does not replace
that profile. Full-five activation uses source642; migration/backend source630;
candidate/authority source631. Do not alias those archive counts or hashes.

Synthetic authority QA used actual keyless SQL verification twice, complete
key/chain checking and two owner-only encrypted Mac copies. The five-member
archive is **genesis-only: zero events**, only the control table populated.
It proves neither production authority retention nor accepted-data recovery,
globally latest accepted head or total-host recovery. No new Drive upload ran.
Retain all existing encrypted copies and associated recovery material; pruning
remains disabled and 30 days is a minimum, not permission to discard authority
needed by any still-restorable manual or automated app copy.

The existing final-image ordinary runtime qualification was recovered read-only
from its retained public server report. Exact original stdout is 3122 bytes,
SHA `74ccbc26b93634bf036af4c83349d6658eff1d52614cbd44771fee70daa99db4`.
It covers accepted flag-off purge, closed restored startup and recovered-ready
startup on image610348. The producer's old field name `runtime195_manifest_sha256`
contains the actual 207-file map; disclose the historical name, not a195 count.
No new ordinary-runtime fixture is required just to recreate that raw receipt.

## Exact unfinished operator state — do not call this qualified

`release-refreeze-v1` is preserved as the closed reviewed predecessor.
`release-refreeze-v2` is **WIP / NOT FROZEN / PENDING**. Start with its
`WIP_STATUS.md`, `PLAN.md`, `operator/`, and the two stop-result files below.
The current candidate and fallback remain pending. No current native guard
actor, transport or archive was prepared or executed before the stop.

V2 adds pure `current_dossier.py`, `current_witnesses.py`, `current_frontend.py`
and current-profile composition of all real components. It binds staged raw
receipts to committed anchors, source-verified helpers, exact runtime/source
counts and the original catalogue DTO consumed by unchanged migration logic.
The complete production execute/recover/postdeploy and original full Config,
HostConfig and mount comparisons remain preserved. The original F1–F4 fixes
remain required.

Two concrete test issues are open, not generic missing context:

1. ROOT ran the original 22 final-gate tests against the latest saved source:
   **21 passed / 1 failed / 0 errors / 0 skips**, source stable during the run.
   The original unchanged method
   `Components.test_original_core_functions_remain_AST_equal` ends by requiring
   preflight bytes identical to the historical base. That expectation is
   superseded by the necessary narrow current-image Env predicate. Preserve
   this exact red and all 22 method ASTs; qualify the reviewed replacement with
   explicit AST/hunk controls instead of reporting22 green or silently skipping.
   `STOP_FINAL_GATE22_ACTUAL.json` SHA
   `259270fae628b880c2dba0d9cd827ad9407525bc0142ea9ab77ff85008ee772a`;
   matching log SHA
   `c2e773c1b966e472f8e3433b12f34b28ec27735bc4318878eb779e5678faef19`.
   The earlier `final-gate22.log` green predates this patch.
2. The latest combined current controls ran74 methods: **73 passed / 1 failed**.
   `test_current_profile.CurrentProfile.test_pending_frontend_ids_never_fall_back_to_historical_images`
   expects default candidate frontend IDs `{}`, while the WIP candidate JSON
   contains actual49e/6e IDs. Resolve the pending-default fixture/contract
   deliberately; no fix was made after the stop. Do not report all current
   controls or a270-case native matrix green.

Current context8, environment/label11 and replacement AST/hunk3 controls passed
in that74-method run; frontend15 separately passed and ROOT reran witness14 and
frontend15. The original162 last passed before the final compatibility patch
and have not been rerun afterward. Latest changed-list Ruff passed. Edited
files were Black formatted, but final full Black--check was not rerun after a
wrong test-file-path invocation. These are the precise remaining validation
limits. Do not reuse older green logs as latest-source qualification.

The image compatibility patch is narrowly justified by actual read-only facts:
backend public image Env and effective command are unchanged; frontend changes
only public NGINX/NJS versions, adds ACME_VERSION and drops the old image's QA
purpose label. Backend drops its old image QA purpose/run labels. Preserve all
private Env strings/order, Compose/runtime labels, commands, HostConfig and
mounts. The wrapper changes expected copies before delegating to the original
full comparison; it is not a generic field-ignore mechanism.

Image ArgsEscaped differs, but actual old and never-started610 **container**
Configs both omit it and have identical effective commands. Keep the container
ArgsEscaped comparison strict. The single never-started probe was removed;
independent receipt SHA
`563eb11dd92dda00b905c8c3800c0f88e5a23e2aadd74646f86b4b2b86d1c23a`
confirms its exact ID/name/labels/mount/volume scope absent and production equal.
It parsed live inspect metadata in RAM; no Env values were exported or persisted.

## Tomorrow's order

1. Read Git status, this checkpoint and `release-refreeze-v2/WIP_STATUS.md`.
   Verify that local ignored evidence is present and its pinned bytes match.
   Preserve every existing red and all original tests/resource limits.
2. Resolve the two specific operator test issues, finish final style checks,
   rerun the affected retained/current controls and freeze the21 operator
   sources plus exact case map. Keep the distinction between real component
   composition and modeled external leaves. No native qualification is saved
   yet. Its proposed historical per-suite ceiling was128 MiB/1 CPU/64 PIDs/60s,
   with shared120s work/30s cleanup; review a concrete packet before ROOT executes.
3. Finish `current-operator/native-guards.json` and the honest same-image
   schema9/delete-off fallback proof. Bind them, all current public components,
   both frontend manifests and the five committed anchors into the final
   current dossier. A status flip in candidate JSON cannot substitute for this.
4. Create the actual final checkpoint/release commit and verify all15 jobs on
   its exact PR head and distinct merged-main head. PR74's passing CI is retained
   component evidence, not the future final release commit. Check current PR
   state before creating or merging anything; stop checkpoint CI may be pending.
5. Complete the minimal Mac full-cutover backup adapter/orchestrator. Read the
   [saved wiring proposal](P11BC_CUTOVER_WIRING_WIP_20261117.md), plus ignored
   `.check-results/resume-20261116/next-release-orchestration/SOURCE_PINS.json`
   and `STOP_STATUS.json` in that directory. This is a step map only: **no Mac
   full-cutover adapter was implemented**. Reuse reviewed crypto/export/actual
   restore primitives with the full operator's19-field app DTO and attest API.
   Backup-only schema8_client_v3 uses a different26-field DTO/run/gate and cannot
   be substituted unchanged. The old Mac controller is schema7/pre-P11a.
6. Only after those gates, run a new fresh app backup plus exact isolated
   restore **inside the full cutover's stopped-writer keeper through0009**.
   Never use backup-only `root_controller.finish`: it resumes schema8 early.
   Full cutover waits330s for the app receipts; the Mac client has300s, so use
   the intersection. Recheck the independent recovery proof's actual24h freshness;
   the old backup-only gate expired and must not be replayed.
7. Actual production authority capture, encrypted Mac readback/keyless SQL
   validation and owner-only retention must complete under the installation
   keeper before writers resume. Its waits240s+30s and maintenance300s do not
   enlarge canonical install's **180s alarm**, which is the tighter remaining
   window. Do not reset shared deadlines. Preserve failures closed.
8. Continue the original guarded migration/install, delete-off ordinary startup,
   actual publisher cycle/cron, activation and public/denial/asset postflight.
   Mark P11 complete only on actual verified production success; update handoffs
   with any failure state before further changes.

ROOT alone integrates and performs SSH/Docker/SQL/private-key operations after
reviewing concrete source. Use the existing verified SSH helper and strict host
key. The sensitive Python runtime is
`/Users/bspear2004/Documents/Aqua/.venv/bin/python` (3.12), with `-E -s -B`;
the default Mac Python3.9 is incompatible. Both complete SSH helper sources
must be hash verified before importing either. Keep owner-only exclusive
staging; a new directory under server SGID2775 may need its own inherited SGID
cleared only after owner/inode verification. Never chmod existing shared or
private paths to make a gate pass. Never print keys, private Env, dumps or rows.

## Separate scope that remains unapproved or unqualified

The current bank product direction is employee help, financial education,
permissioned analytics and human-approved proposed actions. The bank MCP code
is offline foundation only. Rejected SFT results (33→30/67) and weak selectors
(5/16,10/16) do not authorize training, new routing or automatic tools. Preserve
provider/banking-data boundaries. PR70 capacity was synthetic; PR72 optional
PG18 work used public Pagila. Neither proves Tiger/Berka cutover or recovery.

P12 capacity/retrieval and P13 restricted launch remain separate gates. Physical
iPhone/live Google, audience expansion, analytical grants, IdP/MCP activation,
accepted-data encrypted recovery, globally latest accepted head and total-host
recovery are not completed by these results. Do not invent new approval loops
for already authorized routine work, and do not claim these excluded scopes.
