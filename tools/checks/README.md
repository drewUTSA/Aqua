# Reproducible phase security and regression checks

Run these from the repository root on a trusted Linux Docker host or Docker
Desktop using Linux containers. Do not run arbitrary pull-request code on the
production server. GitHub Actions uses an ephemeral hosted runner and no secrets.

```sh
python -m pip install -r tools/checks/requirements-dev.txt
python tools/checks/check_source.py
python tools/checks/check_lock.py
python -m black --check backend eval tools/checks
python -m ruff check backend eval tools/checks
python -m pip_audit --no-deps --disable-pip -r tools/checks/requirements-runtime.lock
docker build --pull -t aqua-checks:p00 -f tools/checks/Dockerfile .
docker pull postgres@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826
python tools/checks/run_backend.py
docker pull nginx@sha256:970364228b1e4f932abc22d321932816782cca8a20b85a77552a7cfe9acfb3b5
python tools/checks/run_proxy.py
```

Then run `npm ci --ignore-scripts`, `npm audit --audit-level=low`, `npm test` and
`npm run build` from `frontend/`. CI additionally runs frontend tests in a
container without network access. Do not enable demo-mode output as real data.

## Isolation and budgets

The backend runner copies only Python, SQL and pytest configuration from known
source directories. It never sends `.env`, Git metadata, credentials, `db/`,
database dumps or eval results. It creates uniquely named PostgreSQL and test
containers, with no host ports, host mounts or Docker socket inside them. The
database has `network=none`; the test container shares only that isolated network
namespace. Both use read-only root filesystems, dropped capabilities, no new
privileges, 1 GiB RAM, two CPU cores and 256 processes each. Writable storage is
bounded tmpfs (512 MiB PostgreSQL data, 256 MiB test temporary files, 64 MiB source).
Docker logs are bounded to two 2 MiB files per container. Each suite has a
120-second deadline; individual commands and startup have separate deadlines.

Only the two synthetic databases exist in this namespace. Their reader role
cannot write or perform DDL; the Pagila fixture additionally restricts hidden
staff columns. The reader's statement timeout is 100 ms to test cancellation
cheaply. Local trust authentication is confined to these disposable containers;
it is **not** the production authentication policy and does not validate passwords.
Fixtures contain no customer data and do not implement the later account DB.

Before application imports, the pytest collection guard discards inherited
service configuration and `PG*` variables and disables dotenv. A fixed dataset
selector replaces arbitrary DSNs. Python network and libpq tripwires detect
accidental calls; the container network boundary supplies actual containment.
These tripwires are not a sandbox for malicious Python code. Native Windows
pytest is not the supported canonical path: Windows asyncio uses loopback
sockets internally. Use the Linux container runner instead of weakening the guard.

The runner removes its exact container IDs in `finally`, verifies absence and
records cleanup failures. Never clean up by a broad name prefix or prune command.
SIGKILL, host failure or Docker failure can still interrupt cleanup: inspect the
specific IDs/names in the report and verify their labels before manual removal.
Images/build cache remain available; no application service is restarted.
The runner is longer than the usual module guideline because creation, execution
and cleanup share one explicit ownership scope; fixtures and coverage parsing
are separate modules/files.

## Locks and evidence

`requirements-runtime.lock` pins the observed Linux/Python 3.12 runtime graph,
with the certifi security patch. Every accepted distribution has a published
PyPI SHA-256 hash. `pip --require-hashes --no-deps` verifies artifacts and
`pip check` verifies the installed graph. `check_lock.py` detects direct
requirement drift. Regenerate/review the Linux snapshot and hashes when changing
requirements; repeat both fixtures and the advisory check. Do not reuse this
Linux-specific lock blindly on Windows. Production `requirements.txt` retains
its existing ranges with a patched certifi floor; deployment lock adoption and
exact deployed-image validation remain part of the release work. Direct check
tool versions are pinned separately; their transitive packages are not claimed
to be a reproducible application runtime.

The runner writes `.check-results/backend/`: JUnit XML, suite logs, package
versions, image IDs, matrix coverage and cleanup status. All tests must pass in
at least one fixture; database-specific skips in the other fixture are expected.
Keep artifacts synthetic and review before sharing. The source scan detects
high-confidence key formats and tracked runtime files, prints metadata only and
exercises a detection/redaction canary. It is not an entropy/history scanner or
a guarantee that every possible secret format is detected.

Official references: [pip hash checking](https://pip.pypa.io/en/stable/topics/secure-installs/),
[Docker resource limits](https://docs.docker.com/engine/containers/resource_constraints/),
[pip-audit](https://pypi.org/project/pip-audit/),
[Ruff rules](https://docs.astral.sh/ruff/rules/).

## Every phase: reproduce, prevent, retest and review

Run the same CI workflow on each PR. Before changing an affected boundary, add
a bounded synthetic attack with a legitimate control case. Keep the failing
baseline separately from the passing retest; an expected baseline failure is
evidence of a finding, never a passing implementation. Add prevention and safe
category logs, assert actual work/state behind the denial, then prove recovery.
Retest all earlier suites when shared auth, routing, storage or cache changes.
Follow `docs/planning/SECURITY_TESTING_PLAN.md` and record not-run/deferred gates.
Do not claim scanner success or a 429 alone proves safe behavior.

`run_proxy.py` exercises the checked-in nginx configuration with two workers,
an in-memory fake upstream and no application/Google/model/email process. Its
containers have the same 1 GiB/two-core/256-process ceiling, dropped capabilities,
read-only roots and exact-ID cleanup as the backend runner. No host volumes,
ports or Docker socket are mounted. Client and proxy share only a network-none
namespace: HTTP is limited to 127.0.0.1:5173 and the fake upstream at :8000.
The probe stops at 100 requests, under 5/second, at most four callers and 55
seconds; individual responses time out at two seconds. It records admission
counters, header/route churn, separate buckets, body limits, concurrent calls and
cooldown recovery. Post-run resource samples are not peak-load measurements.
Its report is `.check-results/proxy.json`; the frontend build remains separate.

For a reviewed vulnerable configuration, `--config <file> --baseline` asserts the
specific forged-header bypass. Never use baseline mode as a release gate or send
it to a public origin. The default mode requires prevention and recovery. The
P01 reports retain both sides of this comparison.

After checks, save source/config/image hashes, package versions, request budgets,
sanitized evidence, remaining deployment gates and rollback steps. Leave the
phase uncommitted for human review, commit/push/PR and merge; do not silently
advance to the next phase. Live ingress, account-level quotas, failure/restart
behavior and capacity must pass their later applicable gates as implemented.

For an exact already-inspected deployment image, pass `--nginx-image <image-id>`
to `run_proxy.py`. This retains the same isolation/budgets and records the actual
image ID; it does not contact live ingress. The October 20 hotfix tested the live
frontend base this way before deployment. Keep CI's default pinned nginx image.
See `docs/implementation/P01_INGRESS.md` for the separate four-request public
smoke scope and the server's uncommitted configuration patch.
