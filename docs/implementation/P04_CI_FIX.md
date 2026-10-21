# P04 CI dependency-order correction

PR #40's first GitHub Actions run (39543915989, head ea71192) passed source/format, dependency, backend, installer and proxy gates, then failed the network-isolated frontend step with `ERR_MODULE_NOT_FOUND: react`. The later install/audit/build step was skipped. The new SSR safety test correctly imports the real React/ReactMarkdown renderer; a fresh checkout has no installed frontend dependencies at that point.

The workflow now runs the existing locked `npm ci --ignore-scripts --no-fund` in `frontend` before the offline tests, and removes the duplicate later install. The audit/build gate remains afterward. No runtime, dependency lock, test, network isolation, Docker privilege/resource flag or workflow permission is weakened or changed.

## Paired verification

A new Linux source directory containing only the 69 committed frontend files reproduces the original missing-React failure using the exact pinned Node image and CI test command. After the locked installation, that same test command passes all **71 cases** with network none, read-only source/root, UID 1000, dropped capabilities, no-new-privileges, 1 GiB memory, two CPUs and a 128-PID cap. The current dependency audit reports no known vulnerabilities, and the production build passes without network access. The lockfile hash is unchanged. Temporary containers and the source/dependency/build directory are removed and absence is confirmed.

The verification helper initially expected Node's TAP-style summary prefix; Node emitted its normal spec prefix instead. Tests already passed, but that evidence assertion stopped before audit/build. Correcting the parser and rerunning from another fresh directory completed the entire sequence. This was a helper-format issue, not a waived application failure. No test or application code was altered.

Evidence: [ci-fix](evidence/p04/ci-fix). Existing P04 backend, migration, attack and recovery results remain applicable because their sources are unchanged. This local equivalent does not claim the repaired GitHub run has passed: the human must commit/push this fix to the existing PR, wait for every check, then review/merge. No commit, push, PR creation, live service/database change or real email is performed here.
