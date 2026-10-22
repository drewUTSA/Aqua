# P05 action boundaries

Each user control remains subject to server authorization. A hidden or disabled
control is feedback, not an access-control boundary. P05 changes browser behavior;
the existing P04 permission, session, database, mail and admission policies remain
authoritative.

Current follow-up: both `opal` and `legacy` builds passed the shared boundaries
below: 120 unit cases, 77 synthetic browser checks per shell and 20 actual-backend
browser checks per shell. Both actual-backend runs naturally recovered from 429,
made no automatic password retries and confirmed complete cleanup. Final reports
are in [P05_ROLLBACK.md](P05_ROLLBACK.md) and `evidence/p05/rollback/`. Earlier
counts below remain historical baseline evidence. Remote CI awaits human push.

| UI action | Trusted boundary | Attack, defense and recovery coverage |
| --- | --- | --- |
| Google/password sign-in | Server identity verification, canonical UUID, durable session and current dataset grant | Forged/extra fields, nonce/CSRF, exact Origin and replay are backend cases; browser checks cover duplicate/late replies, safe wrong-password feedback, disabled methods, provider failure and deliberate 429 recovery |
| Register/recover | Action-specific bootstrap, generic server acknowledgement and durable recipient/global budgets | Email-only initial registration; no initial password or reflected diagnostics; one POST, fresh challenge after manual retry, visible cooldown and no automatic resend. Backend covers enumeration resistance, queued coalescing and finite recipient/global allocations |
| Verify/set/reset password | Purpose-bound single-use mailbox proof, server password policy and atomic epoch revocation | Missing/used/wrong-purpose proof, manager/paste/Unicode support, proof absence from URL/DOM/storage, no automatic login. Both tabs lock at reset start and completion even after a lost reply or interim revalidation |
| Sign out | Durable server revocation before success | Missing/revoked session and CSRF remain backend checks; browser verifies duplicate prevention, hidden/inert retained draft on failure, retry, confirmed discard and cross-tab invalidation |
| Settings/account menu/back | Current canonical account; this shell has no mutation or grant endpoint | Outside/Escape behavior, trigger focus recovery, mobile focus containment, draft/scroll preservation, explicit read-only summary; accounts without datasets may use their own account UI |
| New chat/recents/suggestions | Visit-local ownership, fixed known IDs and 100-conversation bound | Foreign IDs ignored; suggestions only fill the draft; no persistence claim or request from those actions; confirmed account switch unmounts private records |
| Model/send/retry/stop | Server model allowlist, session/CSRF/grant and gateway/shared backend admission | No-dataset UI makes zero query calls; direct forged requests remain server-denied. Existing SQL/AST/Markdown/CSV and rejection-side-effect checks remain. Failed drafts recover; IME and Shift+Enter do not submit |
| Routes/email links | Fixed local route allowlist; proof held only in memory | Hostile redirect/query/fragment, duplicate/malformed proof, network-path-like pathname and same-document proof navigation; public policies/404 stay readable without login |
| Generated answer rendering | Data-only rendering and fixed allowed content policy | Hostile output cannot create executable HTML, active external links or image requests; export formula/control defenses remain covered by unit tests |
| Cross-tab/focus events | Server session response decides identity; broadcast is only a local invalidation hint | No token, identity, CSRF or private content is broadcast/stored; event payload bounded; foreground revalidation at most once per ten seconds; out-of-order responses cannot restore another account's workspace |
| Presentation rollback | Operator build-time allowlist; common auth/account/route implementation | Only `opal` or `legacy`; bad build values rejected; URL/storage cannot choose shell or demo mode; both builds must retain password-only access, CSRF/revocation and cooldown behavior |
| Legal navigation and Back | Existing canonical account owner remains mounted, private view hidden/inert while unresolved | Pending/failed logout through Settings/policy/Back retains locked draft; confirmed logout clears it; direct public policy visits perform no auth bootstrap |
| Visit-local title search | Current owner's in-memory conversations only; no API | At most 100 titles, 512 characters/title and 120 query characters; no body search, network/model work or persistence claim; no-match/clear and cross-account cleanup tested |

## Historical evidence separation

The figures below apply to the initial source, before the rollback/navigation
follow-up. They are not final counts for the changed source or either new image.

- **117 Node tests:** transport, strict envelopes, fixed routes, proof/form policy,
  rendered content and export defenses.
- **56 exact-image browser checks:** real Chrome UI, two tabs, keyboard/mobile
  states and intercepted synthetic APIs. 177 requests/90 API requests, zero
  external attempts, console leaks, runtime errors or forbidden API calls;
  browser/profile/loopback cleanup confirmed.
- **12 fixture mock checks:** defensive cleanup on partial startup and failures,
  including Docker 29's exact-name missing-volume output.
  These validate the test tool, not a product security claim.
- **P04 release enforcement:** 1,056 distinct backend cases across bank/Pagila,
  98 proxy requests, actual isolated PostgreSQL roles/migrations and synthetic
  restore fences. See [P04 release](P04_RELEASE.md) for skips and scope.
- **16 combined real-backend browser checks:** actual FastAPI and disposable
  schema-3 PostgreSQL with fake Google/captured email. 121 requests/66 API requests,
  zero external attempts, console leaks or browser/protocol errors. Browser,
  profile, loopback and all backend resources were removed and absence confirmed.

The combined test's initial old-password login assertion encountered a legitimate
429 after exhausting the server budget. The corrected test explicitly verifies
that denial, waits the real Retry-After, verifies no automatic retry, then requires
401. That full rerun passed. Two explicit fixture-clock steps separate other
scenarios; the exercised cooldown waits naturally. A Docker 29 cleanup-parser
false negative was fixed with a regression, and the complete gate then passed
cleanup. Earlier failed reports remain evidence, not successful runs.

Rate-limit tests cover bounded rejection/recovery and relevant no-work outcomes;
they are not production throughput or denial-of-service capacity certification.
No real model, hosted analytical database, Google callback or account email is
used by the P05 fixtures. Required failed checks block the checkpoint until fixed
and retested. Full settings, imports, chart execution and durable jobs are later
phases with their own action-boundary gates. See [P05 checkpoint](P05.md).
