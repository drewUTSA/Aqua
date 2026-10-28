# Phase9 Homepage

The homepage now concentrates navigation into Projects and Recents, reveals
New Chat after a conversation starts, and places Settings/sign-out in one bottom
account menu. Answers share the canvas and the existing composer compacts after
the first question. A single composer model chooser, optional prompt library
and reduced-motion-aware transitions make the primary workflow easier to use.

Owned chat/project actions, explicit search, archive and draft recovery remain
available through contextual menus. Native dialogs/popovers retain account and
modal boundaries; late prompt responses, newer summaries and deleted-project
drafts preserve current user state. Existing authentication, CSRF, analytical
authority and durable request/cancellation behavior remain in force. No backend
API, migration, dependency or permission change.

Verification is recorded in [the phase evidence](implementation/P09_HOMEPAGE_SIMPLIFICATION.md).
Fresh canonical backend/security/restore/storage/proxy gates pass, including
1,385 backend cases. Final frontend checks pass: 411 unit tests, both production
builds, zero runtime dependency audit findings and all eight browser gates
(514 checks). Twenty current screenshots were reviewed, including 320px with
doubled text. Required PR/main CI and the frontend-only release passed; the
verified release is recorded below.

## Verified release

Merged as `7c0caae8ac0d5fa1c74866bd898d317c1fc984ea` (PR #53,
`Phase9 Homepage`). PR and merged-main CI passed all 29 steps. The October 28
23:10:19 UTC frontend-only release passed exact image/asset and preservation
checks, plus the public sign-in browser. Private schema 5 and the existing
backend/authentication/mail/worker/scheduler stayed unchanged. See
`docs/implementation/evidence/homepage/release.json`; the earlier local-check
record remains immutable evidence of the candidate verification.
