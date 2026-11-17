# Reviewed Aqua help and bounded tool selection

> **Latest session: stopped November 17 UTC.** Read the [complete next-chat handoff](PERSONAL_COMPUTER_RESUME_20261117.md).
> Production remains on schema 8; the current operator is unfinished. Earlier sections retain their historical scope.

This source adds an authenticated, source-cited product-help capability. It is
disabled by default through the separate typed `COMPANION_ENABLED=false` app
policy. It introduces no model call, provider routing, analytical scope, database
migration or trained-model activation. The rejected adapter remains rejected.
The lazy UI and current-image synthetic qualification described below pass
locally; final combined-source PR/main CI remains required before integration.
No deployment or production availability is implied.

## Contracts and useful behavior

- `GET /api/v1/companion/capabilities` returns a closed, explicitly advisory
  menu. `app_help` performs reviewed lookup. `authorized_question`, advertised
  only after a fresh grant check, prepares a draft. It cannot execute a question.
- `POST /api/v1/companion/help` accepts only
  `{"schemaVersion":1,"question":"How do I reset my password?"}`. The response
  declares `method: reviewed_lookup`, `status: answered|abstained`, fixed
  `capability_id: app_help`, a message, source citations and the help-pack hash.
  Unknown or equally ranked topics abstain rather than claiming confidence.
- Data questions retain the existing explicit `submitQuestion` transport and
  durable `Analysis.enqueue` path, which independently reauthorizes current
  owner, session, grant, history revision, admission and requested model.
  A menu, hash, context binding or prepared draft is never authorization.
- Monthly trends are not advertised. Existing numerical trend fitting requires
  trusted units, complete consecutive monthly aggregation and identity; current
  arbitrary chart metadata cannot establish those facts.

The existing offline `eval.companion` API is re-exported from the same runtime
contract implementation. Its original bank/Pagila constraints and disabled
choice receipts remain unchanged. Application help uses an explicitly separate
`application` domain tied internally to the canonical account, initiating
session, auth epoch, history generation and reviewed pack revision. It never
pretends an account without a grant has an analytical dataset.

## Reviewed knowledge lifecycle

`companion/data.py` contains ten small Aqua-authored records, nine active and one
superseded. Guidance covers questions, tables, charts, private history, supported
preferences, account access, password recovery and help privacy. The facts are
adapted from Aqua's existing `CLAUDE.md`, P05 account/auth boundaries, P09
homepage/preferences contracts and exact-result metadata behavior. No GH
business records, source prompts, transcripts or protected evaluation cases are
included. This is a reviewed lookup feature, not neural weight learning.

Only active records with a literal reviewed flag can be searched. The parser
checks the complete reviewed-byte SHA256, strict fields, duplicate keys, text
bounds, known lifecycle states and resolvable acyclic supersession. Altering the
pack requires a new source review and bound digest. Lifecycle labels and a
matching digest bind content; they do not attest who approved it or confer a
permission. Current source review remains the approval checkpoint.

The lookup reuses the existing hybrid retriever's bounded lexical tokenizer.
It returns reviewed text and its exact record citation, without free-form model
generation or a second vector index. A lexical match is not a calibrated
probability. Questions and source text cannot choose an arbitrary tool, SQL,
host, file or write action.

## Privacy, authorization and resources

Help uses the existing `Workspace.reserve` committed account budget, followed by
a fresh `database.guard(data=False)` in a short transaction. It does not call
`Workspace.apply`, submit or interrupt an analysis job, read result rows or chat
history, connect to an analytical database, send mail or invoke a provider.
Accounts without analytical grants can use help. Origin/CSRF, server revocation,
private no-store responses and restore/retirement admission remain enforced.

The new path joins the existing JSON body cap, duplicate-key rejection,
sanitized errors and Uvicorn access-log filter. Its exact nginx location also
disables access logs; generic `/api` logging must not receive help URLs. Unknown
query parameters are rejected and question text travels only in the POST body.
No prompt, help question or private result is cached, logged or persisted by
this feature. Only normal durable account-admission counters change.

Limits are 2,000 characters/8,000 UTF-8 bytes per question, 16 KiB request/pack,
16 records, 2 KiB answer text per record, 16 KiB projected context, at most three
citations (currently one), 32 KiB response and a two-second cooperative service
deadline checked around parsing, admission, the fresh guard and each lookup
record. The input and loop bounds make this deterministic work small; the
deadline does not interrupt an operating-system pause or a database lease.
Existing storage statement/lease deadlines remain authoritative. Both reads
and help actions share the existing 60/account/minute admission allowance.

`companionClient.js`, re-exported through `aquaClient.js`, uses the existing
same-origin `workspaceRequest`. Its optional validated `maxBytes` parameter
keeps the existing 6 MiB default for every existing caller and enforces the
companion's 32 KiB limit before retaining oversized bodies. Existing abort and
history/owner fences remain intact. The consuming UI must abort or discard
responses on dialog close, newer requests and account/history changes, render
messages/citations as data, and seed rather than submit data-question drafts.

## Verification and packaging

The combined source passes680 frontend units and280 isolated P05 assertions per
shell across nine fresh journeys. Opal initial JS is596914bytes, Legacy596916;
both initial CSS files are77367bytes. The lazy help window preserves the same
composer and unsent draft on optional download failure, rejects late replies
after close/new request/history/account changes, closes for Settings, keeps
citations as plain text, handles ambiguity/denial and applies text only after
an explicit action plus current target/draft checks. Its320px/doubled-text
capture was viewed; long internal revision bytes are shortened visually while
the full source revision stays available as citation metadata.

The backend suite passes all eight disposable Bank/Pagila batches,2121 unique
tests per dataset, with restore checks and confirmed cleanup. This local run
preceded Git's LF normalization of three new files; only their line endings
changed afterward. The final source/image and full current CI are separate
gates. Missing build-context admission and source-only test placement were
corrected without widening the backend source archive. The original API/rate/
export/asset prefix hash remains unchanged; the companion's exact private
nginx location follows that retained prefix.

The actual final runtime is
`sha256:61034825653941c528a17bd66d3d0072c18b1a57d82377053d349d6204c7ef66`:
207 compiled files,210 app files and211 complete files including the unchanged
runtime lock. [The actual image inventory](evidence/companion/runtime-inventory.json)
matches every source/asset/lock byte. Its compiled manifest is
`53c6df0e1a6da2ca7d40c3cefe4c11f823ada7472f98e6a75576e62534776d3d`.
The published JSON uses repository LF line endings;
[publication provenance](evidence/companion/publication-provenance.json) binds
those files to the unchanged original local receipts. Runtime/source digests
inside the receipts are unchanged.

[Fresh native qualification](evidence/companion/native-qualification.json)
passes ordinary final-image startup, flag-off accepted purge, restored-history
closed admission, retained-authority app-only recovery and recovered readiness.
A separate fresh installer run passes keeper-held installation, signed head,
bounded export and genesis recovery CLI. Both actual controllers exited and
all disposable resources were removed. Existing running containers and named
image tags stayed unchanged. The source-only QA stages remain private and
retained; no production code/configuration/data was used or changed.

The first normal run exposed a transient empty `/proc` command line at exec
visibility. A separate20-launch actual-image probe reproduced it once. The
fixture now waits only for raw empty bytes while the child lives, sharing the
original12-second startup deadline; wrong/malformed nonempty command lines,
descendants and exited children fail immediately. Four new guards and retained
startup guards pass. Independent review caught and resolved the unterminated-
NUL case. Earlier failure and cleanup evidence remains retained outside the
public source. Runtime application bytes and original overall limits did not
change for this fixture repair.

These are synthetic retained-authority app-only rehearsals. They do not prove
encrypted retention, independent authority total-host restoration or a fresh
production backup. Production stays schema8 with deletion/companion inactive.

The [complete32-call selector research](evidence/companion/tool-choice-research.json)
also failed its quality gate:4b5/16,8b10/16. All failures remain in the denominator
and no proposed tool executed. No model-directed selection is enabled by this
help slice. The separate SQL-trained adapter remains rejected at33→30/67.
More model calls, lower token loss and valid JSON alone are not companion quality.

Focused synthetic tests cover reviewed lifecycle/hash drift, ambiguous lookup,
application/session/history bindings, closed choice denial, deadline expiry,
policy default/invalid flags, real private cookie/CSRF and grant revocation,
restore admission, duplicate/extra/oversized fields, committed rate limiting,
no analytical side effects, private logging and closed runtime packaging.
Client tests cover exact routes, no implicit submission/retry, response schemas,
early Content-Length/chunked byte rejection, the unchanged default transport
cap, abort and late account-switch responses. Existing offline contract tests
are retained. Canonical current-image/backend/browser results are recorded by
the coordinator; source presence is not a passing qualification result.

The Dockerfile explicitly copies the ten companion Python modules. The private
runtime probe records their current SHA256 inventory and checks that private
help paths do not enter logs. Historical runtime/recovery receipts were preserved.
Current qualifier constants bind the inspected211-file image; earlier images do
not qualify it. No dependency lock, migration,
analytical-worker policy, provider configuration or protected test data changed.

## Lazy application UI

The workspace's Help button loads `CompanionToolsDialog` only on explicit action.
It reuses the native `PreferenceDialog`, shared Opal tokens, visible labels,
44px controls, focus containment and safe focus return. Help text and citations
are plain React text; Markdown, HTML, arbitrary links and provider reasoning are
not rendered. Loading, unavailable, error, denied data capability, answered and
abstained states have distinct copy. A default-off server returns an honest
unavailable dialog with Close and an explicit availability check.

The controller aborts and discards superseded or closed reads. It clears state
on close and history/owner invalidation; the mounted account/private-deletion
boundary and route/active-chat changes unmount the dialog. Settings and hidden
workspaces do not retain it. Apply to composer draft is an explicit button: it
checks the current authority, target chat and unchanged original draft, calls
only the existing draft setter, closes and requests composer focus. It does not
submit a question. Opening, reading and closing help leave the original composer
node, draft and IME/input behavior intact. Optional chunk loading/failure has its
own native closeable boundary and cannot unmount the workspace.

The new dialog, hook/controller and CSS stay in the lazy optional chunk. Build
qualification must prove the existing 600,000-byte initial JavaScript and
80,000-byte initial CSS ceilings without increasing either limit.

Ask data also offers an optional local question guide. The user supplies a
required measure and optional grouping, period and filters. Each plain-text
field is bounded to400 characters; the final review draft retains the normal
2,000-character/8,000-byte question ceiling. Unknown optional details remain
explicitly unspecified, with an instruction not to invent details or units.
The UI asks the user to review them; it does not claim that the SQL-only analysis
engine can conduct a clarification conversation. Prepare draft for review changes only the existing editable
textarea. Field changes invalidate the prepared state and held help responses;
the user must prepare again or explicitly edit the draft. Write freely remains
available. Only the existing explicit Apply can replace the unchanged composer
draft, followed by the ordinary separate Send. The guide makes no request,
checks no company schema, persists nothing, and cannot select or execute tools.

Full local units, both production builds and all nine isolated P05 journeys per
shell pass as recorded above. The final guided journey has20 assertions per
shell, including required input, explicit preparation/review/apply, stale guide
invalidation, zero analytical submissions and320px doubled-text reflow. Actual
computed input text is32px at200% scale; fields retain labels and44px targets.
The opt-in synthetic journey
is `p05-browser.mjs?journey=companion-tools`; it adds no production flag and keeps
the existing 240-second, 900-request and 320-API ceilings. Its fixture simulates
only the two help endpoints and never opens an analytical database or provider.
It covers literal citations, abstention, default-off/denied capabilities, explicit
draft-only apply and conflict, close/newer/owner/history/settings late-response
fences, 320px/doubled text and an intentionally blocked optional chunk.

The reviewed UI/CSP source and companion source were reconciled in
`Workspace.jsx`, `QuickSwitcherBoundary.jsx` and `p05-browser.mjs`, retaining
the Settings/prompts/shortcut boundaries and every original browser journey.
The final full-source PR/main CI remains a separate required acceptance gate.
