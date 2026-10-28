# P09: add safe account and device Settings preferences

Settings previously displayed a placeholder. This change adds nine navigable,
searchable categories with supported appearance, workspace, chat, chart/table,
accessibility and regional formatting choices. Account values persist through an
authenticated revision-checked API; device values use separate bounded browser
storage. Safe changes preview in a shared draft until explicit Save or Cancel.

Reset/import dialogs show scoped changes before applying them to the draft.
Versioned JSON import/export excludes identity, credentials, instructions,
conversations, results, consent and permissions. Invalid/oversized/duplicate-key
imports are rejected atomically. Conflicts, lost responses, partial scope failures
and local-storage failures retain recoverable drafts and report confirmed scopes.
Existing chat drafts, conditional visuals, source values and analytical permission
checks remain separate from presentation changes.

`GET/PUT /api/v1/me/preferences` uses the current authenticated owner, ordinary
Origin/CSRF/session checks, a complete closed account schema and compare-and-swap
revision. Reads/writes share the existing durable 60/account/minute workspace
budget. Future or unsupported stored choices fail closed and are preserved.
P10/P11 credential/session/notification/private-data operations remain unavailable;
unsupported response-style/language/instruction/default-model controls are not
presented as working settings.

## Verification

Canonical backend verification passed **1,385 unique cases** across the isolated
bank/Pagila fixtures, including owner/session/CSRF enforcement, atomic revision
conflicts, abuse-budget recovery and incompatible-record preservation. Synthetic
restore preserved preferences while fencing sessions and abandoned jobs. Source/
lock, Black/Ruff, pinned runtime audit, image-byte proof, private-storage role/
installer checks, telemetry/privacy probes and isolated proxy checks passed;
test resources were removed and existing running containers were unchanged.

The verified backend is
`sha256:5ff0cb141a3399f95458cc20fcadfbe66577e750702fd74ba6238716d7c99897`,
with 119 matched runtime files and unchanged schema 5. Its verification archive
is `719f0719c34d8ae9f720d1612c76b2f65f960587a44f5c1062e603cbbe94991d`.

The complete frontend suite passed **399/399**. Both final production builds and
bundle gates passed; Plotly stays lazy and the frontend dependency audit reported
zero vulnerabilities. All eight final browser gates passed on the verified asset
sets: each shell passed 103 synthetic, 39 real-workspace, 41 Settings and 37 actual-
Plotly assertions. Each Settings run covered 128 measured presets, both system
theme modes, forced colors/reduced motion, browser accessibility-tree checks,
all nine categories at 320 CSS pixels with actual 200% control text, safe imports/
conflicts and keyboard/focus behavior. Actual Plotly checks ran with a saved Table
default to verify explicit chart requests take precedence. Every gate confirmed
browser/profile/listener/backend cleanup, with zero external attempts, live
provider calls, runtime errors, console leaks or protocol failures.

Native reverse-Tab escape from the modal, fixed light-theme header/input colors
and narrow input/header/file-picker overflow were corrected and retested through
the complete final browser matrix. Eight selected synthetic screenshots were
visually reviewed; the [portable evidence](implementation/evidence/p09/verification.json)
records hashes, measurements, prior failed attempts and fixes. Representative
reviews include [Opal desktop](implementation/evidence/p09/screenshots/opal-settings-desktop.png),
[legacy light](implementation/evidence/p09/screenshots/legacy-settings-light-increased.png),
[320px / doubled text](implementation/evidence/p09/screenshots/opal-settings-320-double-text.png)
and [actual Plotly](implementation/evidence/p09/screenshots/legacy-desktop-actual-plotly.png).

CI now runs actual P09 Settings checks for both shells, retains bounded synthetic
reports/screenshots and tests explicit charts against a saved Table default.
Changed-file source-policy checks passed. YAML parsing and all 20 Bash run-block
syntax checks passed with existing action pins/permissions/concurrency preserved.
Required PR and merged-main CI subsequently passed; PR #52 merged as `05accec`.

See [the phase record](implementation/P09_SETTINGS_PREFERENCES.md) for the
requirement/evidence map and explicit unavailable capabilities. Settings is complete and deployed. The phase record includes exact release images, CI and controlled production verification. No production restore or live-provider/load benchmark is claimed.

## Compatibility and rollback

No migration, dependency, provider credential or role change; the existing private
schema-5 preference table is reused. Applied migrations 0001–0005 remain immutable.
Roll back backend/frontend together to reviewed P08 images while retaining schema
5, preference rows, private volumes and the active account-mail configuration and
worker. A rollback must not delete user choices or restore obsolete auth.
