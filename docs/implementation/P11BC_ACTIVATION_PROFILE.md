# P11b/c activation profile — prepared, inactive

This is the reviewable installation sequence for the current schema9 source.
It authorizes no installation, production DDL, secret generation or upload.
The source-integrated deletion feature remains off. Actual source-bound kernel,
mount, backup and recovery evidence must replace every pending gate below.

Read-only host metadata on 2026-11-05 found ext4 at the disposable QA directory,
SSH UID/GID1000, no effective capabilities, Docker socket root:108 mode0660,
and no host writes or Docker actions during that inspection. This shows a
plausible test filesystem; it does not prove append protection or durability.

## Immutable installation inputs

Freeze the reviewed schema9 runtime, every installed byte, migration checksums,
both frontend builds, host launcher/code manifest and operator helpers. Run the
complete retained backend matrix, original capacity case, native80 protocol
cases, mail63 cases, both real deletion-browser journeys and schema9 storage,
proxy and restore checks. Require zero unexpected skips and confirmed cleanup.
Record actual native image IDs; tags and source-level promises are insufficient.

`ops/retirement/publisher_launcher.py` remains deliberately disabled and pins an
old schema8 image. Its `PENDING_STORAGE_AND_RECOVERY_PROOF` code digest must not
be bypassed. A separately reviewed profile must replace its image and five-file
verified host-code manifest only after the corresponding schema9 image/runtime
proof and the gates below pass. Preserve network-none, UID1000, read-only root,
no capabilities, one checkpoint connection, 55-second/55-step bounds, exclusive
publisher singleton and verified-byte import-before-key-read behavior.

## Host layout and access separation

Use separately created owner1000, mode0700 directories below the fixed private
retirement root. All regular private files are owner1000, mode0600, one link;
keys are exactly32 bytes. Creation is exclusive, never replace an existing
installation or normalize unsafe metadata silently. Fsync new files and parents.

| Host directory | Contents | Container access |
| --- | --- | --- |
| `authority/` | append-only `checkpoints.bin` only | signer: directory RW; backend: file-only RO |
| `backend/` | `backend.json`, HMAC `identity.key`, empty checkpoint/mail mount targets | backend: directory RO; never signer |
| `host/` | checkpoint-only `host.json`, Ed25519 signing seed | signer: directory RO; never backend/mail |
| `recovery/` | recovery-role configuration, external head fence and restore receipt | offline operator only |
| `code/` | reviewed five-file host-code tree and exact manifest | signer: RO |

The backend mounts `backend/` read-only at `/run/aqua-retirement`, then overlays
the real authority checkpoint **file** read-only at `checkpoints.bin` and the
existing account-mail physical **file** read-only at `mail-worker.lock`.
This satisfies the current verifier's private/read-only parent requirement
without exposing HMAC/writer credentials to the signer's writable directory.
The signer mounts only `authority/` at its own `/run/aqua-retirement`; that
directory contains no backend secret, mail key or SMTP environment. The same
virtual pathname in different containers does not imply a shared secret mount.

The existing account-mail launcher retains its exclusive singleton and acquires
SH on `PRIVATE/physical.lock` before Docker create. Its worker receives that same
inode RO at `/run/aqua-mail-physical/worker.lock` and launcher-generated decimal
DEVICE/INODE fields. Neither field may come from worker.env. The backend uses
the same source inode for EX through account-purge commit. Verify Docker mount
metadata and descriptor/path identities before/after create/start, not filenames
alone. Once installed, neither feature flag may disable these admission fences.

## Installation transaction and resource budget

Keep writers and scheduler closed and prove old web/download/analysis/mail
children have actually exited. Take and verify the ordinary stopped-writer
encrypted application backup using its existing recovery-key procedure.
Apply only migration0009 through the existing reviewed migrator. Do not edit
previous migrations or run schema DDL on shared analytical databases.

Install a separate `aqua_retirement` logical database through the reviewed
create-only bootstrap/schema scripts, never an application dump restore.
Keep owner NOLOGIN, three execute-only roles at one connection each, DB cap4,
no PUBLIC/temporary/create privileges, no app-role CONNECT, and synchronous
commit/fsync/full-page-writes on. Add only explicit local-socket HBA rules.
Normal app-runtime maximum is9 connections (web4/export1/download2/deletion1/
mail1), below12; authority writer1 and checkpoint1 are separate. Offline recovery
uses its own one connection while normal writers remain closed. A future backup
role must be explicit, read-only and inventoried within the independent DB cap;
the existing execute-only recovery role cannot perform a complete pg_dump.

Generate installation/key UUIDs, HMAC identity key, Ed25519 seed and distinct
43-character role passwords only inside the eventual reviewed local installer.
Never put credentials in argv, reports, Git, logs or chat. Public manifest values
are installation/key UUIDs, HMAC key commitment and Ed25519 public key. Create
and fsync the signed sequence0 record, set the real inode APPEND flag through a
separate minimal-capability step, verify by ioctl, then run the publisher's full
scan and actual synchronous genesis acknowledgement. No acknowledgement may
escape before the protected append/fsync and SQL commit/readback both succeed.

## Native durability gates

`python tools/checks/run_retirement_durability.py` is source-bound preparation
only: zero writes/Docker actions. After the coordinator releases the serialized
native slot, its explicit execute mode accepts only an exact image ID and exact
source fingerprint, and creates a fresh owner-only QA tree. The flag setter has
only LINUX_IMMUTABLE/FOWNER/DAC_OVERRIDE, no network or Docker socket, and sees
only that tree. The signer probe has no capabilities. Cleanup stops its actual
container before clearing only the disposable flags; uncertain cleanup stays red.

Required evidence: actual GET/SETFLAGS; a fresh nonappend open/write cannot rewrite;
O_TRUNC/ftruncate/unlink/rename/rename-over/flag-clear fail; the bind-mount root
cannot be replaced; a real signed208-byte append/fsync preserves every prior
byte; malformed appended tail fails closed. APPEND does not prevent an authorized
signer from appending garbage: such a failure remains maintenance, never truncate
or auto-repair the protected chain. This gate does not claim disk power-loss
testing, mail-mount proof or full independent SQL composition by itself.

The first native counterexample is retained: ext4 APPEND did **not** revoke a
nonappend writable descriptor opened before the flag was set. Therefore the
create-only `ops/retirement/initialize.py` runs in a separate process/container,
closes/fsyncs every write descriptor and must be removed with absence confirmed
before the flag setter. The setter opens the file read-only, sets/readbacks the
flag and exits before the signer container is even created. A new empty authority
and O_EXCL inode creation prevent reuse of an existing install. No write fd may
be inherited or passed between these phases. The existing launcher checks APPEND
before Docker create; its Docker client explicitly closes other descriptors.
No preexisting-descriptor revocation is claimed. Retrofitting APPEND onto an
already admitted signer is forbidden; older negative evidence is not relabeled.

Also require the real two-DB route/publisher/seal/purge/app-only-restore/grant
composition on this actual protected inode, without the existing named ioctl
seam. Inject failure after fsync but before SQL ACK commit, then prove restart
acknowledges the exact existing signed head without another append. Kill the
isolated mail sender's DB session and its launcher during a blocking fake send;
the actual worker's same-inode SH must keep web EX denied until sender exit.
Never use lease age, a missing DB row or a dead Docker client as exit proof.

## Independent retention and closed recovery

The ordinary backup recovery key copied privately to Drive is a different
artifact. It does not authorize uploading retirement keys or ledger data.
Separate offhost destination authorization and an encrypted restore challenge
are still required before any such upload. The protected archive must include
the complete independent SQL state, full signed chain, HMAC identity key,
Ed25519 recovery seed, exact public profile and schema/role/source pins. Prove
decryption and full chain/key commitment with a fetched independent copy, using
synthetic challenges rather than disclosing secrets. Do not retain plaintext
dumps. A backup can contain identities and requires the same private boundary.

Retain authority/keys/checkpoints through **every still-restorable** application
copy, including manually held copies. Configured30-day retention with pruning
disabled is not a30-day upper bound; there is no tombstone expiry. A periodic
copy cannot prove that no newer deletion was accepted before total-host loss.
Require an independently retained latest-accepted-head fence, or keep disaster
recovery closed until the newest accepted authority is recovered. A rewound
ledger plus matching old checkpoint is not evidence of completeness. Current
app-only restore safety does not assert total-host RPO0 replication.

Offline recovery first proves all old children stopped, restores only the app,
applies the existing restore-session fence, validates the retained latest signed
head, then calls `retirement.recovery.reconcile` with the separate recovery role.
It must stream all events and sealed original pages, reconstruct original floors,
retain staging intent maintenance, revoke restored receipts and settle bounded
physical cleanup before readiness. Never reconstruct a smaller original manifest
from an older backup. Repeat recovery idempotently with writers still closed.

A schema9-compatible fallback must retain the installed authority, startup/grant
checks, generation fences and physical lock with new deletions disabled. Rehearse
the exact fallback image against accepted deletion and app-only restore. The
historical schema8 P11a export fallback cannot serve schema9 or enforce deletion.
Enable new deletions only after all source/runtime, kernel, mount, independent
retention, backup recovery and fallback evidence is reviewed together.
