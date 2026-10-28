# P09 homepage simplification

Status: implementation and current-source verification are in progress. P09
Settings is separately complete and deployed as `05accec` (PR #52). This
supplement is not released by that Settings result. Required browser, PR/main
CI and controlled frontend release gates must pass before completion.

## Behavior

Navigation contains Projects and Recents, with saved ordering/visibility and
bounded pagination. New Chat appears with a short fade after the current
conversation starts and hides on a blank conversation. Project folders expand
one server-capped page on explicit action; chats support rename, move, archive,
restore and confirmed deletion through their item menus. Recents provides
explicit title search, archived chats, refresh and visit-local draft recovery.
Deleting a project preserves its chats and ungroups an unsent local draft.

The bottom account entry contains the only visible Settings/sign-out menu.
Sign-out requires confirmation and retains the existing server-revocation and
failure-preservation behavior. One model chooser lives in the composer at all
viewport sizes; selecting a model affects the next explicit question. Only
server-advertised names and descriptions are shown. Saved prompts and optional
starter questions open from a composer tool. Applying a prompt seeds text;
it never submits a question.

Answers share the page canvas. The same composer becomes more compact after
the first question, grows with its draft and stays in the existing conversation
flow. The textarea, selection/IME handling, per-chat drafts and reading position
remain intact. Requested visuals still open on the right, retain their own data
controls and follow the existing mobile tabs. Short menu, section and composer
transitions respect device and operating-system reduced-motion preferences.
Menus support keyboard traversal, focus return and bounded viewport placement.
Typography follows text resizing, including menu labels and confirmation copy.

## Security and state boundaries

The owner/Origin/CSRF/CAS routes, analytical authority, durable request identity,
cancellation and resource budgets remain in force. No new backend API,
dependency, migration, provider action or client-side permission is introduced.
Projects use validated owned summaries; history and mutations still enforce
ownership on the server. Only one expanded project page is cached. Lazy prompt
loading avoids background library requests on initial home.

Native dialogs and popovers stay inside the mounted account/modal scope and
close when their authority or navigation ancestor is hidden/inert. Nested
saved-prompt editors use the same boundary. A delayed prompt-use response cannot
seed text after its dialog unmounts or after the selected chat/draft changes.
Selecting a newer project summary preserves local text and pending work;
confirmed project deletion does not rewrite an in-flight submission.

## Verification and review

Fresh canonical Linux checks passed source/lock, Black/Ruff, dependency audit,
both disposable database fixtures, all 1,385 unique backend cases, runtime byte
proof for 119 installed files, telemetry/privacy, restore, storage and isolated
proxy denial/recovery. Cleanup was confirmed and the pre-existing running
containers stayed unchanged. The new verification image is
`sha256:37f25df779a17d74867fbfbf2088040b1edd944bfd93eee1e4ab7011830c4bbe`.
The deployed P09 backend has the same application source and remains the
frontend-only release baseline.

The final source passed 411 frontend unit tests, both builds and strict
source/asset manifests. The locked runtime dependency audit reported zero
vulnerabilities. Initial delivery is 554,047 bytes of JavaScript and 77,730 bytes
of CSS, within the unchanged 600,000/80,000 byte limits; Plotly remains lazy.
All eight browser gates passed on the final assets: 136 synthetic, 43 real
workspace, 41 Settings and 37 Plotly checks for each shell, 514 total. Twenty
current screenshots were reviewed. The gates retain the original request/time/job limits and test
ownership, CSRF, literal hostile inputs, revoked grants, durable work, cancellation,
deletion/late completion, real Settings and precision/visual behavior.

New journeys cover conditional New Chat, a single account/model entry, model
selection without submission, composer identity/compaction, draft and reading
position retention, project deletion with a draft, late prompt use, nested-dialog
privacy, keyboard menus, 320px reflow, actual doubled text and reduced motion.

Historical failures are retained separately. Early harness repairs replaced
removed inline selectors with contextual menus, generated complete native Enter
events and awaited lazy Settings readiness. Product review fixed native
top-layer suppression, newer summary selection, deleted-project local drafts,
safe confirmation focus, New Chat icon contrast and scalable menu text. No
passing result from the earlier Settings release satisfies this supplement.

## Release and recovery

Published as `Phase9 Homepage` after local gates passed. Required checks on the
exact PR head and merged main passed before release. Future recovery must package only the final
browser-verified assets, prove their source against the merged Git object and
compare the full static/nginx image set. Recreate only the frontend. Preserve
the healthy P09 backend container/image, database, private volumes, environment,
worker and scheduler; restore the exact P09 frontend image if verification fails.
No database restore or obsolete-auth rollback is part of this frontend change.

P10 account/security implementation stays separate. ChatGPT-like organization
uses AQUA's existing private projects/chats contract; project files, shared
workspaces and cross-project model memory are not introduced.

## Verified release

Merged as `7c0caae8ac0d5fa1c74866bd898d317c1fc984ea` (PR #53,
`Phase9 Homepage`). PR and merged-main CI passed all 29 steps. The October 28
23:10:19 UTC frontend-only release passed exact image/asset and preservation
checks, plus the public sign-in browser. Private schema 5 and the existing
backend/authentication/mail/worker/scheduler stayed unchanged. See
`docs/implementation/evidence/homepage/release.json`; the earlier local-check
record remains immutable evidence of the candidate verification.
