# Workspace improvement record — November 13, 2026

## Scope and candidate

Ben requested substantial application improvements informed by prior Aqua
discussions, GH Logistics projects and available skills, retaining the tests.
This first reviewable slice is on `codex/aqua-workspace-navigation`, based on
main `9aeaf4eb91a4db55d3701e8be872f2b1e178a116` (PR #57). Changes are local and
uncommitted. This record does not complete P11 or establish production state.

## Sources and decisions

Reviewed the Aqua root/planning handoff checkpoints, README, CLAUDE guide,
P10/P11 progress, export activation boundary, frontend workspace, list-loading
and dialog contracts. Relevant available chat history included the Aqua bank
application discussion and the November 13 GH context/workflow review. This was
a targeted context review, not an exhaustive review of every past conversation.

GH references were read only: the November 13 repository map, shared workflow
state/preflight rules, and QA's `web/src/components/DriverLookupPanel.jsx`.
The useful QA principles are explicit human selection, visible lookup scope,
and distinct unavailable/unknown/empty states. Adapt those principles to Aqua;
do not import GH operational data, provider wiring, credentials or tenancy.

Applied redesign/accessibility guidance, the workstream evidence/preflight
skill and computer-use browser review. Retain Aqua's approved Opal appearance,
both shells, ownership boundaries, SQL safeguards and existing verification.

| Previous behavior | Change | Purpose |
| --- | --- | --- |
| Navigation requires sidebar/menu discovery | Header quick switch and Ctrl/Cmd K | Reach frequent actions and loaded chats from either shell |
| Recovery is inside the Recents menu | Draft/pending entries precede saved chats in the switcher | Resume work without sending or retrying it |
| Composer focus requires pointer navigation | `/` outside editable controls | Start a question using the keyboard |
| Old search pages can outlive a filter change or failed read | Bind page criteria and distinguish loading/error/empty/matches | Avoid reporting stale results as current matches |
| Typed search and applied search can look identical | Label the actual applied query | Explain which query produced the displayed page |

The switcher uses at most 100 recovery and 100 recent entries already held by
the mounted owner, deduplicates them, searches titles/descriptions only and
shows at most 20 matches. Search accepts at most 120 characters, folds accents
and uses all query words. It has no storage, telemetry, network search, private
message indexing, new dependency or background provider call. A separate explicit
action opens the existing authenticated title search for older server pages.
Demo copy explicitly describes visit-local data.

Navigation uses the existing unsaved-preference guard. Modal/hidden workspaces,
composition, repeat and modifier combinations suppress conflicting shortcuts.
The native dialog retains Escape, Tab containment and focus restoration. Actions
are buttons; arrows and Enter support quick selection without overriding Home/End
editing in the search field. Neither selection nor opening a draft submits it.

## Verification

**Latest delivery correction:** The unchanged browser gate separately caps CSS
at 80,000 bytes. The first JavaScript repair still delivered 80,495 CSS bytes, so
`c5d2e45` correctly failed. Only the header's shortcut styles remain initial;
dialog styles now load with the dialog. The offline artifact guard enforces the
same 600,000-byte JS / 80,000-byte CSS ceilings before browser startup. Three new
regressions prove exact limits pass and one extra JS or CSS byte fails. All 614
frontend tests pass (600 retained, eleven workspace cases, three budget cases).
Final local builds deliver 591,684 JS bytes / 79,295 CSS bytes in Opal, and 591,686 /
79,295 in Legacy. No existing browser assertion or ceiling was changed.

The first integrated navigation browser gate caught an initial-script budget
regression: `e357a0e` delivered 601,319 bytes against the retained 600,000-byte limit.
The keyboard policy now loads separately from the on-demand switcher index;
the shared search dialog no longer has a redundant self-import wrapper, and the
demo's hook/seeded history loads only when demo mode opens. The Opal initial
script is now 591,593 bytes (Legacy 591,595), including the optional-download
recovery boundary, with no limit raised and all 611 tests still passing.
Demo, account ownership, draft state and both shells require their existing
browser qualification on the resulting head. The earlier failed CI is retained.

An isolated static demo explicitly returned 503 for `QuickSwitcher-*.js` and
made every API unavailable. The real browser displayed “Shortcuts unavailable”;
closing it retained the unsent composer text and restored focus without sending.
This tests the actual rejected module and local recovery boundary, not a mocked
React error. The separately loaded demo also bootstrapped normally. The owned
loopback server and screenshots belong to the task verification directory; no
production file or account was used. Full authenticated/browser CI remains required.

After integration with the P11 deletion and P12 retrieval branches, the earlier 611
frontend tests pass: the retained 600 plus these eleven regressions. Both Opal
and Legacy production builds and their existing bundle guards pass; the locked
frontend audit reports zero known vulnerabilities. This is local integrated
verification. Final exact-head PR/main CI and deployment remain separate gates.
The 575-test checkpoint below describes the earlier pre-P11 source.

All 564 original frontend tests passed unchanged before adding regressions.
Added policy and real-component rendering cases cover title-only indexing,
owner input replacement, deduplication, bounds, hostile-title escaping, demo
truthfulness, keyboard suppression and stale/failed/loading/empty search states.
The final local frontend run passed 575 tests: all 564 existing tests plus 11
new regression cases, with zero failures, cancellations or skips.

Production builds for Opal and Legacy and the existing Plotly manifest/byte
checks passed. No dependency/lockfile, existing test assertion or budget was
relaxed. The offline source guard and runtime-lock consistency check passed.

Local synthetic demo browser review exercised opening/filtering the switcher,
arrow/Enter chat selection, Ctrl K from the composer, Escape/focus restoration,
retained unsent text, empty-match fallback, explicit applied search, Settings
navigation, the unsaved-preference guard and shortcut suppression inside it.
The modal was visually reviewed at the default desktop size and 390×844.
The viewport override was reset. This does not certify screen-reader support,
200% zoom, real-account isolation or all existing browser/release gates.

Docker's Linux engine was unavailable. The canonical backend, proxy, disposable
database and full authenticated browser matrices were not run. Live services
were not used as substitutes. Review is self-review, with independent review
and the existing release gates still pending. No production state is asserted.

## Next improvement sequence

1. Finish P11 exports/deletion release and recovery requirements using current
   source/evidence; reconcile the handoff's older PR #56 code checkpoint with
   merged PR #57. Keep merged, deployed and enabled distinct.
2. Extend source/result provenance where users make decisions: dataset, requested
   versus actual model, saved-result age and exact-value controls. First audit
   existing `ResultMetadata`/analysis controls to avoid duplicate UI or invented
   freshness guarantees. Test with both authorized and revoked-result fixtures.
3. Measure P12 workflows before optimizing: login delivery, large-history lists,
   chart opening, cancellation, slow streams and pool saturation. Record p50/p95,
   resource ceilings and representative hardware; retain all current limits.
4. Review empty/loading/conflict/retry states across all nine Settings sections,
   keyboard-only use, 200% text and narrow screens. Keep each change reviewable.
5. Complete P13 hardening, policy/contact accuracy, recovery evidence and the
   restricted rollout checklist before broader audience activation.

These are priorities, not claims of implementation or a measured tenfold gain.
Rollback this navigation slice with a source revert and matching frontend
rebuild. It introduces no migration or backend flag change.
