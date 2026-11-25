# Dependency audit for review item 13

On November 25, 2026 at 17:52 UTC, both package advisory services returned zero findings for the dependency locks from Aqua commit `d0adb6f16f3086abab00921afe2f2edb27df2da9`.

| Audited input | Tool | Coverage reported | Advisory IDs, affected versions and available fixes | Exit |
| --- | --- | --- | --- | --- |
| `tools/checks/requirements-runtime.lock` | pip-audit 2.10.1 | 49 pinned runtime packages audited, zero skipped | None reported | 0 |
| `frontend/package-lock.json` | npm 11.20.0 on Node.js 26.13.1 | 154 packages reported, zero informational, low, moderate, high or critical findings | None reported | 0 |

From the repository root, the Python check used the existing environment and treated each pin in the runtime lock as an explicit audit target. The frontend check ran from `frontend` and included development dependencies. The following commands print the same JSON reports to standard output.

```sh
python -m pip_audit --no-deps --disable-pip -r tools/checks/requirements-runtime.lock --format json
cd frontend
npm audit --audit-level=low --json
```

| SHA-256 | Python | Frontend |
| --- | --- | --- |
| Input lock | `cad37d805664670589892c601592623d3a2b73e7c80147e3b7695e2a113339a7` | `6a4a3345bdbe4a9ac0a003a7ebea8bf8fd85677eab6debf14241ba431adb8c7d` |
| Retained JSON response | `f4474fc15427b22768646f3dc36b6bff9ac64582cac987373eaadf2f1a5bfffd` | `28834468fb32af207abe3a3b2357345e0dd2766eb3a1d243de7cbdbbb0b4bea3` |

These results cover package advisories available at the time of the scan. No package installation, upgrade or lockfile modification was needed.
