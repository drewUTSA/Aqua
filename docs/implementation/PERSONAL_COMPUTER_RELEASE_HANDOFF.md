# Personal-computer release handoff — November 13, 2026

## Resume instruction from Ben

Ben requested completion of the remaining phases and useful AI improvements,
preserving the existing tests. On November 13 he directed that recovery-key
discovery and the backup/recovery work be handed to his personal computer, where
the existing key probably resides. Continue implementation and isolated
qualification; do not migrate production or activate deletion before that
computer supplies a fresh verified backup and the required recovery evidence.

Read this record with the root handoff, `CLAUDE.md`, `P11_PROGRESS.md`,
`P11BC_ACTIVATION_PROFILE.md`, and the current PR/CI state. Historical evidence
does not qualify a different source, dependency graph, image or environment.

### Office integration checkpoint

PR58 merged as `19d031e4733a468fd61c14b2b0403cbafd28b222` and PR59 as
`79fc1294ee8048df0df3e6cbb4092017a36c40e6`, each after all nine exact-head
PR jobs passed. PR60 carries the workspace improvements and this expanded
handoff. Its initial-script regression was repaired under the unchanged
600,000-byte JS / 80,000-byte CSS limits: Opal 591,684 JS bytes and Legacy 591,686,
both 79,295 CSS bytes, with all 614 frontend tests passing locally. The initial
stylesheet regression and its failing CI remain recorded; the build guard now
checks both retained ceilings before browser startup. A real rejected shortcut download was also
rehearsed in an isolated demo; the workspace and unsent draft survived.

Final PR60 and combined merged-main CI must be read from GitHub when resuming.
These merge facts concern source integration. Production remains on the
verified P11a/schema8 release; P11 recovery/activation, broader P12 capacity/model
evaluation and P13 launch gates remain incomplete. No office merge activates
deletion, public registration or a new Google audience.

## Verified connection and production baseline

The server is Tailscale node `2004`, currently `100.83.237.33`, SSH user
`ben2004`, project `/srv/bank-ai`. The earlier LAN address `192.168.1.200`
was unreachable from the office PC. Its Tailscale connection works.

The office PC (`Richard-Station`) has Tailscale, a dedicated client key and
`aqua-codex` SSH alias. SSH uses Tailscale's `nc` proxy because direct Windows
TCP routing did not work. Strict host-key checking remains enabled. Key-only
login and the separate Docker context `aqua-codex` were verified. The default
Docker context was not changed. Never copy this PC's private key into Git or
assume it exists on the personal computer.

On the personal computer, reuse its existing connection/key where possible.
The historical Windows identity path was
`C:\Users\Benjamin\.ssh\aqua-work-20261016\id_ed25519`; later backup work ran
on the Mac under `/Users/bspear2004`. These are discovery clues, not instructions
to recreate or overwrite keys. Verify actual platform, paths and ownership.

```sh
tailscale status
ssh -T aqua-codex 'id; hostname; cd /srv/bank-ai && git status --short --branch && git rev-parse HEAD'
```

Use an existing known host identity, or establish it through the authenticated
tailnet peer. Do not disable checking, replace a changed key without investigation,
expose SSH publicly, or modify unrelated server access.

Read-only server verification on November 13 found:

- Clean main checkout `9aeaf4eb91a4db55d3701e8be872f2b1e178a116`.
- Internal readiness returned ready, private application schema **8**.
- Healthy backend image `sha256:dec35c031486fbb5a16cf823bd14073d704f507c94c1c1cbbaa71a6acd4b5962`.
- Healthy frontend image `sha256:4fab90c0016ab600fc11e337766cee54b5ee22e4d2330f6829502bd28f41adcb`.
- Docker 29.1.3; about 33 GiB filesystem space available at inspection.
- No production `/home/ben2004/.aqua-runtime/retirement` installation.

P11a exports were already released on November 6. Older main-branch notes saying
production is still P10/schema7 are stale. Deletion/schema9 is not deployed.

## Find and verify the existing recovery material

1. Discover the existing personal-computer backup directory and reviewed
   controller. Inspect file metadata and configuration paths without printing
   recovery credentials. Do not search or paste private-key contents into chat.
2. Locate the recovery identity referenced by the November 5 independent-copy
   proof, including the owner-only private Google Drive copy if necessary. The
   current connected Drive account is `spear.g.benjamin@gmail.com`; metadata
   searches from the office task did not locate that recovery file. This is an
   access/discovery gap, not proof the key is gone. Preserve existing backups,
   identities, repositories, credential helpers and retention settings.
3. Verify the identity's derived public recipient and decrypt a fresh bounded
   synthetic challenge using an independently fetched copy. Record only hashes,
   public recipients, owner/permission facts and pass/fail receipts.
4. The newer recovery identity does not decrypt older backups encrypted with an
   unavailable predecessor. Keep that limitation explicit. Never label all
   historical backups recoverable based on one new-key challenge.

The reviewed authority backup implementation is under
`ops/retirement/backup_client/`. Its vendored host/stream primitives and pinned
manifests came from the earlier Mac controller. Read their platform/path and
permission contracts before invoking them. Porting them to a new platform needs
isolated tests, rather than deleting ownership, process, byte or deadline guards.
The old Windows Restic command in `ops/appdb/README.md` describes a different
historical backup foundation; do not silently substitute it for the current
reviewed age/authority recovery workflow.

## Required before the schema9 production cutover

1. Refresh the exact PR head and its complete nine-job CI result, merge only
   after required checks pass, and require a distinct passing merged-main run.
   Preserve reviewable phase boundaries and current work in other checkouts.
2. Freeze the exact backend/frontend images, complete source and dependency
   manifests, migrations, operator stage and schema9-compatible fallback.
   Rehearse that fallback; the old schema8 image cannot enforce deletion.
3. Verify the single web process, bounded pools, socket volumes, current database
   identities, environment hashes, mail worker configuration and scheduler.
   Take a preservation baseline without displaying private values.
4. Close writers and prove physical exit of web/analysis/export/download/mail
   work, using the reviewed maintenance and physical-lock protocol. Keep the
   original mail singleton lock held. Do not treat a lease timeout as exit proof.
5. Stream a **fresh current production application dump directly into encrypted
   off-server storage** using the existing verified recovery recipient. No
   plaintext dump on disk, in terminal output, in Git, or in chat. Require the
   producer's exit code, byte/deadline bounds and authenticated decrypt/hash
   verification; prove restoration only in disposable isolated storage.
6. For the independent retirement authority, use the create-only reviewed
   installer and exact image/source profile. Protect its checkpoint inode only
   after the initializer exits, then admit a new capability-free signer. Do not
   retrofit APPEND around a preexisting writable descriptor.
7. Independently retain the complete authority SQL state, signed chain, identity
   HMAC key, signing recovery seed, source/profile pins and latest accepted-head
   fence. Use the explicitly approved private off-host destination and encrypted
   capture/restore challenge. Ordinary app-backup key storage does not alone
   establish authority retention or permission for a new sharing destination.
8. Apply only additive migration0009 to private application storage. Preserve
   prior migrations and all analytical/Tiger data, grants, volumes and credentials.
   Verify exact mounts, physical mail inode, authority role separation and startup
   fencing before any writer resumes. Follow the activation profile's budget.
9. Enable new deletion requests only when all installation, recovery, retention
   and normal-runtime gates pass together. Verify public GET-only delivery and
   denial boundaries. Keep Google audience and business-data grants unchanged.

Retention is 30 days with pruning **disabled**. Authority protection must cover
every still-restorable copy; there is no automatic 30-day tombstone expiry.
RPO24h/RTO4h remain targets until measured. Total-host recovery stays closed
without an independently established latest accepted head and complete keys/
ledger coverage. App-only recovery with retained authority is a separate claim.

## Continue P12 and P13

### First action in the personal-computer chat

Open the actual Aqua checkout and give Codex this instruction:

> Read `AQUA_CODEX_HANDOFF.md` and
> `docs/implementation/PERSONAL_COMPUTER_RELEASE_HANDOFF.md`. Resume the
> November 13 office work. Preserve current changes and all tests. Discover this
> computer's existing recovery identity and backup controller using metadata
> first; do not display secret contents or replace older backups/keys. Verify
> the exact PR/main state and complete the remaining isolated recovery, capacity
> and launch gates before proposing the concrete production cutover.

The user has deliberately deferred key discovery from Richard-Station. An
empty search here is not a reason to generate replacement identities or claim
older backups are lost. If an identity cannot be found on the personal computer,
report that precise gap and preserve every existing backup before choosing a
future-only key. A new key does not recover ciphertext encrypted to an old one.

### Current code and evidence pointers

- PR58: `codex/aqua-p11-deletion`; exact latest complete CI is required. Its
  prior `73270e4` run hit the outer 20-minute job limit after eight jobs passed;
  `dfe2734` gives that sequential job 30 minutes without changing inner limits.
- PR59: `codex/aqua-p12-ai-reliability`, initially stacked on PR58. Read
  [P12 progress](P12_PROGRESS.md) for actual source/runtime pins, the 1,854-test
  Linux result and synthetic graph/history/metadata/pool measurements. Current
  CI still governs integration. Real model accuracy remains unmeasured.
- `codex/aqua-workspace-navigation` contains the preserved office navigation
  work integrated with P11/P12. Its 611 frontend tests and both builds pass.
  Read [P13 progress](P13_PROGRESS.md) for the current no-go decision and public
  header/discovery observations. P13 is preparation, not a completed launch.

Use GitHub's current PR heads/checks and source inventory as truth when resuming.
These branch names and earlier receipts are discovery pointers, not authority
to deploy a stale image or replay a migration blindly.

The office workspace contains a navigation slice on
`codex/aqua-workspace-navigation` and bounded retrieval-graph improvements on
`codex/aqua-p12-ai-reliability`. They are separate from PR #58; inspect their
actual status before integration. Preserve all existing test identities and
budgets, add targeted regressions, and qualify both UI shells.

P12 requires real synthetic capacity measurements, including deep history,
provider/cancellation/stream stages, pool saturation and recovery, chart/bundle
costs and model/retrieval quality. A graph microbenchmark is only one component.
P13 requires the complete hardening, truthful policy/contact, backup/restore,
restricted-rollout and final review evidence. Do not mark deployment, enablement,
public signup, a measured accuracy gain or a phase complete based on source alone.
