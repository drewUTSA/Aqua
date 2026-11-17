# Prepared local-model qualification — November 16, 2026

> **Latest session: stopped November 17 UTC.** Read the [complete next-chat handoff](PERSONAL_COMPUTER_RESUME_20261117.md).
> Production remains on schema 8; the current operator is unfinished. Earlier sections retain their historical scope.

This is an opt-in synthetic generation experiment, not a deployed provider,
training job, retrieval-quality result or completed P12/P13 gate. No real
inference result is claimed by this source. Root review and isolated checks
precede execution. No inference is added to CI.

## Closed scope

From a trusted checkout, the default command only prints a plan:

```text
python tools/checks/run_local_model.py
```

Only explicit `--execute` can create disposable fixtures and request inference.
It requires an exact pre-existing local Docker image ID, an expected installed
model digest and a new report path outside the source checkout:

```text
python tools/checks/run_local_model.py --execute --image sha256:REVIEWED_LOCAL_IMAGE_ID --expected-model-digest REVIEWED_INSTALLED_QWEN3_4B_SHA256 --output NEW_PRIVATE_REPORT.json
```

The sole provider is existing `qwen3:4b` through strict key-only `ssh aqua-codex`
to server-local `127.0.0.1:11434`. Each call checks `/api/tags` against the
required digest before POST `/api/chat`; a returned reply must name exactly
`qwen3:4b` and have `done: true`. There is no model/host/path override, pull,
installation, service restart, fallback, Gemini call or provider key. Model
inventory is server-reported evidence, not independent weight attestation.

The remote helper runs with an empty environment except a fixed PATH. The
Windows SSH client inherits only `SystemRoot` and `PROGRAMDATA`; read-only SSH
preflights found both necessary on this PC. No proxy, credentials, PATH or
profile environment is forwarded. Other platforms use an empty environment.
SSH uses the existing owner-controlled client configuration/key and pinned host;
no key or configuration is copied into this checkout.

## Actual production components, synthetic data

The original network-none PostgreSQL fixtures and read-only analytical role are
reused. The ordinary 300-second regression runner is removed with absence
confirmed; a separate model runner has a 1,080-second lifetime and the same
1GiB/two-CPU/256-process/read-only/no-capability/tmpfs limits. No host port,
host directory, Docker socket, private environment or live DSN is mounted.
Both images must already exist, and every model-harness create adds
`--pull=never`; it cannot implicitly download a missing image.

Production `generate_sql`, prompt construction, Ollama request options,
response parsing, SQL AST validation and read-only execution stay inside that
Linux runtime. Preparation uses a capture-only HTTP client, validates gold
against independent synthetic fixture facts, and emits only the production
request. The stdlib host broker forwards that request. Scoring replays the
bounded response through the same provider/generator code and rejects a
changed request digest before executing validated SQL. Gold SQL and expected
rows are never included in the model request. Prompts and raw replies are
ephemeral; reports contain identifiers, statuses, measurements and digests.

The selected cases are frozen by source/dataset digests: four training pilot
cases, then the first twelve answer test cases per dataset from the reviewed
replay artifact, twenty-four test cases total. Frozen-rank security scenarios
are excluded from model accuracy; the existing independent security tests
remain required. All four pilots must succeed before any holdout request.
Pilot scores are not mixed into test accuracy. Every unsuccessful or unfinished
test remains in the fixed 24-case denominator.

This experiment measures **first-attempt** SQL generation. It deliberately
uses `think=false` and production `NON_THINKING_OPTIONS` (temperature0.7,
top-p0.8, top-k20, seed42), context16,384 and output4,096 tokens. It does not
exercise the pipeline's repair loop or claim the production default's behavior.

## Deadlines and honest cancellation

Only one request may be active. The experiment permits at most32 provider
attempts,45 seconds per SSH/provider transport,120 seconds per case and a
900-second **inference window after provisioning**. Provisioning retains the
existing fixture's startup/per-command bounds. Cleanup is separate, with15
seconds per exact-ID removal/absence check. These are not a claim of a single
900-second total wall-clock bound including setup/cleanup.

Remote SIGALRM bounds complete metadata/HTTP handling; a local subprocess
watchdog uses the smaller remaining transport/case/run allowance. Prompt text
is capped at64KiB, provider bodies at1MiB and extracted SQL at32KiB. The fixed
remote helper is frozen once per experiment and its actual source hash is
retained alongside the source archive and dataset digests.

**Closing SSH/HTTP does not prove Ollama's daemon/GPU generation stopped.**
Any transport timeout, incomplete reply or unverified remote work permanently
stops the broker and the entire experiment; there is no retry or later call.
The failed current case retains elapsed time and attempted-call count; later
cases are separately marked not completed. Remote physical exit remains
unknown rather than being inferred from a closed client process. The runner
does not cancel/unload a model or reconfigure a shared service.

Fixture limits do not constrain server Ollama RAM/GPU consumption. Confirm
the shared provider's suitable operating window before execution. `/api/ps`
and host memory observations can inform that decision but do not prove that no
other user is issuing requests. Stop on contention; do not alter service
capacity or production fallback policy to make the test pass.

## Offline acceptance before inference

```text
python tools/checks/test_local_model.py
```

These tests use fake SSH/HTTP responses and exercise default no-op behavior,
closed policy, immutable expected digest, response identity/completion,
terminal timeout, exact call/concurrency caps, Windows environment whitelist,
pilot/test separation, missing-image denial and create-only evidence.
The two `backend/tests/test_local_model_capture.py` cases require the pinned
Linux runtime and test production request/response binding without networking.
Finally, qualify prepare/score for all28 selected cases in an owned network-none
fixture using known synthetic replies, including SQL denials and request-digest
mismatch, with cleanup verified. These are fixture checks, not model results.

P11 backup/authority retention/schema9 activation, broader P12 workload and
held-out retrieval qualification, and P13 release review remain unchanged.
No model result can authorize production activation or new dataset access.
