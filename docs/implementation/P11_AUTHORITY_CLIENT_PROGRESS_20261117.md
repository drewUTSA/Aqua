# Optional authority-client release safeguards

The prepared full-cutover operator needs one inherited deadline across capture,
encrypted readback and the actual SQL restore callback. Previously, collection
started a fresh300-second window and recovery used separate120-second allowances.
The new optional API intersects the original install start+180seconds, owner,
client and run ends from one caller monotonic clock. Each operation recomputes its
remaining cap and reserves existing cleanup time; late results deny. No original
timeout, receipt field, native-adapter type check or default call shape changes.

An optional independently pinned exporter route verifies the complete21-module
source closure before any exporter module executes, then serves eager/lazy sibling
imports from verified immutable RAM bytes. It fixes the isolated `python -c`
import-path problem for the future reviewed operator without adding an unverified
directory to `sys.path`. See [the API and exact limits](../../ops/retirement/backup_client/OPT_IN.md).
The default CLI still performs no actions. Neither the route object nor a matching
hash authenticates a producer or authorizes activation.

## Actual qualification

- Original closed56 model/process tests and29 new tests passed as separate exact
  inventories in a network-none, read-only Linux UID1000 container:128MiB,1CPU,
  64PIDs, no host mounts or ports. Work completed in6.047seconds after metadata
  hardening, with confirmed source stability. This source is stacked
  onto the synthetic MCP source; exact known container ID and name absence were
  confirmed. Original vendor/verifier manifests and the56-test runner remain
  byte-identical. [Raw final receipt](evidence/authority-client/linux-models-20261117.json).
- The earlier pre-hardening API/helper version passed a pre-stack run in4.282seconds. That
  receipt retains the earlier workflow binding, distinct from the final combined
  workflow. [Pre-stack receipt](evidence/authority-client/pre-stack-linux-models-20261117.json).
- Fourteen actual Linux filesystem/bootstrap cases passed for the packaged route:
  eager/lazy synthetic imports, independent pins, helper/source mode, parent mode,
  symlink/hardlink denial, tampering and no unlisted disk fallback. This uses the
  image's Python executable in place of the server's `/usr/bin/python3`; the
  isolated flags/bootstrap are exact. [Route receipt](evidence/authority-client/linux-route-20261117.json).
- The first two Linux model invocations failed before container creation because
  Docker's optional image `Config.Volumes` key was absent. The harness now uses an
  optional-key projection and still requires null volumes. Both failed receipts
  are retained as `metadata-template-failure-{1,2}.json`; neither ran the suites.
- Root separately ran the earlier27 new pure/model methods on Windows and reviewed
  the final metadata fix; the focused final29 cases passed in existing environments.
  Black/Ruff, source/secret and whitespace checks passed. CI runs pure budget/route
  tests without runtime dependencies and integration tests in a separate environment
  installed from the existing hashlocked runtime lock.

The final review found a file-metadata race: initial owner/mode/one-link checks
could pass, then post-read descriptor/named observations compared only inode,
size and mtime. A link/permission change could therefore violate that metadata
contract while the independent content hash still passed. Both the normal reader
and bootstrap now bind owner, full mode, link count and ctime before/after reading.
Directory identity is unchanged, allowing unrelated directory timestamp changes.
Reader mutation cases and two new bootstrap methods verify rejection before helper
compilation with no input echo, plus the permitted directory-timestamp case.
The old27-case/Linux-route receipts and all15 CI jobs at2e5406a are retained as
pre-hardening evidence only. Fresh exact-head and distinct main CI are required.

The [publication provenance](evidence/authority-client/publication-provenance.json)
records original raw and newline-normalized publication hashes separately. Only
CRLF-to-LF conversion follows the repository's cross-platform text policy; parsed
JSON and all outcomes are unchanged. Original raw receipts remain retained in the
private qualification workspace. Hashes establish byte identity, not attestation.
The local driver was a separately reviewed private qualification harness. These
tests execute models and synthetic modules, not the actual exporter, age pipeline,
native SQL restore, production authority or a full cutover. Required exact-head
and distinct merged-main CI remain outstanding for this source increment.

## Remaining release gates

The unavailable Mac ignored operator/raw component proofs were not recovered.
Current retention/readback contracts, a complete source-bound operator, enclosing
hard deadline, fresh authenticated stopped-writer backup, independent retained
authority recovery, actual exporter/native full-cutover qualification and a
schema9-compatible deletion-off fallback remain required. Cooperative deadline
checks cannot preempt CPU/filesystem work or prove remote cleanup. The future
operator must retain an honest stopped/unknown failure state and requalify its
entire source closure. No production source, image, schema, model, environment,
key or service was changed by this increment.
