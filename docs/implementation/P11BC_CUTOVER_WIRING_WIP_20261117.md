# Full-cutover orchestration proposal

> **Latest session: stopped November 17 UTC.** Read the [complete next-chat handoff](PERSONAL_COMPUTER_RESUME_20261117.md).
> This is a saved source-only wiring proposal. It is not a qualified production driver.

## Check a schema 10 candidate

The historical plan below stops at schema 9. The current backend requires schema 10 and its default migrator applies both `0009_retirement_deletion.sql` and `0010_context_notes.sql` when upgrading schema 8.

Before using a proposed release plan, enter **its declared starting and target versions** in the public stage tool. Supply the intended backend image digest and the independently reviewed SHA-256 of the same public source archive used by stage preparation. For a plan targeting schema 10 from schema 8, run this command from the checkout.

```sh
python -B tools/checks/prepare_retirement_stage.py \
  --check-schema-transition 8 10 \
  --backend-image "$CANDIDATE_IMAGE" --source-sha256 "$SOURCE_SHA256"
```

The check compares the archive's migration, migrator and readiness source bytes with the named runtime image profile. An 8-to-9 plan against the schema 10 runtime exits with an error. A compatible plan prints the two pending migration checksums and `release_eligible: false`. The check reads public checkout source only. The running database version, actual image contents, fallback rehearsal, independent recovery receipts, stopped-writer attestation and final release approval each require their own evidence.

Stopped at the user’s request. Source review only; no Mac adapter was implemented.
No command below has run. The production writer owns the
entire `cutover.py` process; the Mac supplies only the awaited receipts. This is
the existing release flow, not a replay of the completed backup-only ceremony.

## Inputs before starting

ROOT freezes the current operator sources and `candidate-pins.json` after its
qualification. The reviewed candidate is still PENDING: `commit:null`, `ci:{}`,
empty evidence/model maps and no release dossier SHA. The eventual checkpoint
PR and its **distinct merged-main** run must each pass all 15 exact jobs; use
that final commit, not PR74/main `3fd413c` as an assumed final release commit.
PR74/main remain qualified component/source provenance. `current_profile` checks
no backend/frontend/ops/tools/workflow source delta from the qualified source.

ROOT stages a new owner1000/0700 server directory
`/srv/bank-ai/.check-results/p11bc-release-<17digits>-<8hex>` matching `PINS.run`,
with create-only owner1000/0600 metadata and exact reviewed code. Required inputs:

- Current operator guard closure, `candidate-pins.json`, `baseline-lineage.json`.
- `source.tar` candidate631 SHA `8e819ffeab930f17fe0af490d0248c4d0c673ce591d51b070ee9d6f3fc5daaae`,
  `manifest.json` SHA `9bfdf6a394fe986a185e6606477d1b72e61e532e7ae73f0743789f15401d0c38`,
  exact extracted `source/`; backend/migration proof630 SHA `560872d6…` stays distinct.
- Five committed `current-*-20261117.json` anchors, current-release-dossier.json,
  its exact `components/<COMPONENTS path>` raw proofs, both `frontend-{shell}.json`,
  current runtime manifest and current frontend source339 tree.
- Exact P11a baseline release/deployment receipts and seven-job baseline lineage;
  no baseline image or historical proof is relabeled as a candidate proof.
- Actual current guard qualification and same-schema9 delete-off fallback receipts,
  plus public image metadata compatibility/representation receipts.

Both native frontend images are qualified: Opal `sha256:49e4ab58…`, Legacy
`sha256:6e2c98c2…`; selected manifest must match the selected exact full image ID.
Backend is `sha256:61034825653941c528a17bd66d3d0072c18b1a57d82377053d349d6204c7ef66`.
Private recovery key/proof/ciphertext paths remain ROOT inputs outside checkouts;
no private material belongs in this packet or terminal output. Reuse the verified
SSH host/key helper00fb and stream helpere558; no ambient SSH configuration.

## Existing entry points and order

Server argv for both `server-preflight.py` and `cutover.py`/`deploy.py` is:

```text
/usr/bin/python3 -E -s -B <SERVER_STAGE>/<entrypoint>
  --commit <FINAL_MAIN_COMMIT>
  --frontend-image <EXACT_SELECTED_IMAGE>
  --frontend-manifest <SERVER_STAGE>/frontend-<shell>.json
  --runtime-manifest <SERVER_STAGE>/<CURRENT_RUNTIME_MANIFEST>
  --frontend-source-root <SERVER_STAGE>/<CURRENT_FRONTEND_SOURCE_ROOT>
  --evidence-dir <SERVER_STAGE>
```

Run only through a ROOT-reviewed bounded pinned-SSH foreground driver. Keep the
foreground server process alive throughout both handshakes. `deploy.py` simply
calls `cutover.main`; it is not a second deployment workflow. `server-preflight`
is read-only. Checkpoint staging/checkout update and final CI freezing are ROOT
preparation outside this operator; preflight requires a clean exact checkout.

| Phase | Existing server owner | Mac/ROOT response | Awaited server file |
| --- | --- | --- | --- |
| Preflight | `gates`, `preflight`, create-only activation-input checks | Exact final dossier and source/CI bindings already staged | No fresh backup yet |
| Stop schema8 writers | outer release singleton; mail launcher EX; pause exact original mail cron; stop both old frontend/backend; acquire physical mail lock; confirm schema8 idle and no migrator/worker | Consume fresh `attest.py show`, pin run/nonce/PID/old IDs/commit/stopped time | `cutover-state.json` is server-owned |
| Fresh app recovery | `writers_stopped`; `wait_for_files(...,330)` rechecks real attestation | Encrypt fresh export, authenticate same bytes, actually restore matching dump in isolation, verify ACL/fence/repeat and exact cleanup; only then construct full-cutover app DTO and retained-owner ACL proof | `backup.json`, then `retention.json` through `attest.py receive-*` |
| Commit migration9 | recheck attestation/stopped database; strict-HBA recreate same app DB container over same data/socket volumes; compare schema8 preservation; apply0009 in exact native610 migrator; compare all35 old protected tables+new4/catalogue | No finish/resume command; Mac keeps server owner alive | Server state progresses through migration-started/schema9-committed |
| Install/retain authority | release only parent mail/physical claims while outer singleton, paused cron and stopped OS writers remain; `install.execute(...,retain=callback)` obtains its own GLOBAL/launcher/physical/publisher locks | Consume fresh authority attestation/head and exact export profile. Authenticated archive includes both keys locally; only dump+public chain go to real keyless SQL restore. Retain encrypted copy and independently fetch/read back, retaining owner-only metadata | `retirement-backup.json` and ROOT's separate `retirement-readback-pin.json`; then `retirement-retention.json` |
| Reconcile while stopped | callback prepares recovery profile under same keeper; installer returns writers/cron still stopped; actual retained-authority recovery CLI proves ready; parent reacquires mail/physical | Confirm this same keeper/source/head/receipt lineage | Server state authority-reconciled |
| Admit schema9 | actual publisher cycle; persistent publisher cron; retirement mounts; start current pair with deletion OFF; verify; pause/wait publisher, stop pair, enable deletion and worker retirement, install exact resumed schedule, start pair, verify public postflight | Independently retain final sanitized deployment receipt and inspect stated preservation/safety result | `p11bc-deployment-<UTC>.json`; state verified |

`attest.py` API is `show`, `receive-backup`, `receive-retention`,
`receive-retirement-backup`, `receive-retirement-retention`, each `--root SERVER_STAGE`.
Receipt stdin is ≤16384 bytes and publication is create-only under an owned input
flock. Acknowledgements identify the exact accepted action. ROOT separately
publishes `retirement-readback-pin.json`; there is no `receive-readback` action.

## Existing budgets, not enlarged

- Cutover state lease1200 seconds; real PID/boot identity and paused cron checked.
- Fresh app files wait330 seconds. The new Mac app adapter must intersect this
  with the existing300-second client end, not restart either clock per phase.
- Existing app encrypt/decrypt ≤120 seconds each, export plaintext≤512MiB.
  Current matching isolated schema8 restore stays16MiB plaintext, work≤120 seconds,
  cleanup≤60 seconds, PG17 tmpfs128MiB data/1MiB socket/16MiB temp, memory/swap512MiB,
  oneCPU/128 PIDs, read-only/network-none/no ports/caps/persistent host mounts.
  All children and cleanup also fit the inherited app end; maxima are not additive.
- Stop uses Docker stop40/command55 seconds; migration attach90 seconds, 512MiB,
  oneCPU/128 PIDs; DB recreation health40 seconds; pair health75 seconds.
- Authority keeper300 seconds, authority wait240+30 seconds, **installer hard
  SIGALRM180 seconds begins before setup**, so that remaining180 window is tighter.
  Do not allocate240/300 fresh after seeing the wait message. Authority capture
  preserves120-second operations and193MiB archive/128MiB dump/194MiB cipher caps;
  actual SQL callback requires more than45 and at most120 seconds. Clip all work
  to the existing remaining installer/keeper deadlines; uncertainty stays stopped.
- Actual publisher launcher remains55 seconds (host work55, cleanup reserve inside),
  publisher exit wait60; no budget or fixture/resource assertion is broadened.

## Exact DTO seams that still need the new bounded Mac adapter

The full server accepts **19 fields**, `label=pre-p11bc`, schema8, filename
`pre-p11bc-YYYYMMDDTHHMMSSZ.pgdump.age`, final checkout commit, current full release
run/guard/nonce/old IDs/stopped time, authenticated decryption, dedicated recovery
identity, no plaintext file and `actual_isolated_restore:true`. It checks stopped
≤started≤created≤now and created age<600 seconds. Full retention is exact14 fields,
version1, same run/commit/nonce, SHA of exact accepted backup bytes, same cipher
SHA, directory+ACL hashes, outside-checkout/owner-only, no plaintext,30-day policy.
The byte/hash/identity restore binding remains in the new Mac private evidence;
only the exact server DTO projection is published after actual restore passes.

The completed backup-only `schema8_client_v3` uses a different26-field contract,
`schema8-backup-*` gate/baseline, old deployed commit and `pre-schema9` microsecond
filename. Its paired `root_controller` sends **finish and reopens schema8**; never
invoke it for this full cutover or before0009. The old Mac P11a controller is
schema7/pre-p11a and cannot provide the modern restore flag. The existing restore
core is reusable but its old record contract/plan path must be adapted explicitly;
never fabricate the passed flag or overwrite the completed drill's private plan.

Authority capture APIs exist (`Expected`, `Transport`, `bridge.collect`,
`bridge.verify_recovered`, exact `NativeSQLAdapter`), but the default bridge CLI
is deliberately no-action. The passed `capture_readback` driver is QA-only and
rejects production/session routing. A production wrapper still must project the
closed full-server authority DTO and publish the three distinct files above.
Canonical `remote_command` routes to SERVER_STAGE/ops/retirement/export.py; full
cutover itself creates the retained controller elsewhere. ROOT staging/transport
must explicitly bind that module closure and its import path (the Python `-c`
bootstrap does not prepend the script directory), or use a separately reviewed
fixed retained-controller route. Do not substitute the QA transport silently.

Authority backup must join all `RETIREMENT_BINDINGS` from the live keeper/head,
full-chain/both-key proof, exact keyless SQL receipt/source/dump/head, directory
identity/permissions and ciphertext. ROOT's nine-field readback pin is independent
of the retention DTO and binds exact backup-record/cipher/directory hashes plus
its independently checked readback receipt. Only afterward may sixteen-field
retirement retention use the pinned readback SHA, same record and30-day policy.
This is capture-point authority retention; latest-accepted-head and total-host
recovery remain false. No producer may attest to its own independent ROOT check.

## Failure ownership

Any failed/missing/stale receipt or lost owner causes the full operator to pause
known schedules and independently attempt both writer stops. It never rewinds a
schema9 database, reopens the old schema8 runtime or deletes partial authority.
Read the actual redacted deployment result, confirm maintenance independently and
continue ROOT recovery if uncertain. Do not use backup-only finish as recovery.
