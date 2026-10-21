# P01 merged release verification

October 20, 2026, Chicago (October 21 UTC). PR [#37](https://github.com/drewUTSA/Aqua/pull/37)
merged at `07055eb4579f2bfb002d252942805b8d853fbdb8`. GitHub Actions run
`39528817735` succeeded. Local main and server `/srv/bank-ai` were fast-forwarded
to that commit. The server's existing `.env.bak` was preserved without reading it.

The server's only tracked difference was the previously authorized nginx hotfix.
Its private rollback copy was preserved, and the incoming config was verified to
match after CRLF/LF normalization before restoring that duplicate and merging.
Linux nginx SHA-256: `544dccf718c4a64420323c5a89a7fca04c2f315697d15e300c4873e90868ab2a`.
The existing Cloudflare routes still send both hosts to `127.0.0.1:5173`.

## Dependency drift caught before deployment

An ordinary backend build resolved newer dependencies from ranges. Exact-image
tests caught a real regression in `LIMIT ALL` handling; the release was stopped.
The retained red fixture reports are evidence of that failure, not successful
verification. Rebuild using the already-reviewed hash-locked graph, including
SQLGlot 30.21.0 and pinned Python 3.12.14; all 727 distinct backend tests then
passed across both isolated fixtures. No SQL safety check was weakened or skipped.
P02 makes that same locked-build policy reproducible in the production Dockerfile.

The verification also checked all 32 packaged backend source files against the
merged revision, ran `pip check`, and exercised the actual frontend image with
the bounded 31-request two-worker proxy test. All passed; test resources and clean
source contexts were removed. The first attempt refused an ignored local venv
symlink; the verifier switched to a clean Git archive, retaining that guard.

## Deployment and smoke scope

The exact checked images were deployed with health checks and rollback images:

| Component | Deployed image |
| --- | --- |
| Backend | `sha256:9069a33c2bb0588308d49371e38f872fb9d95a540208622c3f127203d28e4d1d` |
| Frontend | `sha256:982f1b5b43cd24026b01a92532548fde025d68dc3a59e423342ac7811b003292` |

Both services are healthy. At `2026-10-21T01:58:10Z`, a four-request public smoke
confirmed `/api/health` returned 200 with `no-store` and an oversized synthetic
request to a nonexistent API path returned 413 on **both** public hostnames.
Budget: four requests, at most two/second, six-second response timeout. No login,
model, mail, authenticated query, private data or database migration was invoked.
This proves the observed deployment/ingress boundaries, not every production flow.

Rollback image tags `aqua-p01-rollback:backend` and `aqua-p01-rollback:frontend`
retain the prior images. Their IDs are in the deployment report. If a rollback is
needed, preserve the corrected nginx/tunnel routing and verify it again; do not
restore a direct API bypass. No root/sudo permission was added by this release.

Evidence is retained under [evidence/p02/p01-release](evidence/p02/p01-release).
P02 is prepared separately on `codex/p02-private-storage`; its uncommitted source
and disposable tests do not change this live P01 release.
