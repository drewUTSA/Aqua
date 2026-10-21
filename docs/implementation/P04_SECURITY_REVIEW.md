# P04 follow-up: unwanted mail and executable content

This review responds to the request to prevent mass email abuse, incorrect account messages and executable user/model content. It strengthens the uncommitted P04 candidate before its human PR checkpoint. P03 remains live at schema 2. No real email, hosted business-database access, schema-3 production migration or feature activation is performed by this review.

## Account mail is a fixed security workflow

The only messages implemented are mailbox verification, a requested password-reset link and a notice after a successful password reset. Google sign-in does not require these local password-verification messages. There is no public send-email endpoint, free-form recipient list, submitted subject/body/template, marketing workflow or AI email tool. Chat content and query results are not email payloads.

The sender and provider endpoint are fixed. Message text and subjects must match one reviewed template for the exact purpose. The worker rejects an envelope with a mismatched subject, extra link, changed origin, noncanonical recipient or altered metadata. Link origins come from validated server configuration, never request Host/forwarding headers or a submitted redirect. Recipients are validated single ASCII mailbox addresses. Enqueue verifies the token digest, challenge purpose, mailbox, expiry and current reset-account state/epoch; the delivery selection rechecks that the associated challenge is still eligible. This catches implementation mistakes as well as refusing malformed submissions. AEAD prevents a database-only attacker from rewriting a pending payload without its separate key; it does not protect against compromise of that key/application.

| Control | Enforced bound |
| --- | --- |
| Duplicate requests | At most one pending/sending logical job per normalized mailbox and verification/reset purpose; a repeated request does not invalidate the original valid link |
| Recipient cooldown | At least five minutes between new logical messages for that mailbox/purpose |
| Recipient daily history | At most three new logical jobs in a **rolling** 24-hour interval for that mailbox/purpose; three timestamps are stored independently of challenge/outbox deletion |
| Shared history storage | At most 4,096 recipient-purpose keys; batched expiry cleanup, no active-key eviction to create a fresh allowance |
| Request admission | Existing peer, normalized-address and global budgets persist across workers/session changes |
| Provider delivery | At most one attempt/second, 20/hour and 60/day across workers, including retries; purpose allocations reserve reset/security capacity |
| Retry behavior | Same job/body/idempotency key, at most three attempts, bounded backoff and lifetime; no retry after proof expiry or the provider deduplication safety window |

Recipient suppression returns the same generic acknowledgement and does not expose account eligibility. The rolling history and cooldown survive worker restart and deleting a consumed proof/mail job. Verification cannot spend the reset allowance or suppress a successful-reset security notice. A notice requires a completed reset in the public workflow; submitting an invalid proof creates no notice. Recipient/history limits and pending coalescing run under the existing short mail-admission lock; equality/indexed seeks and fixed-size timestamp lists keep the extra work bounded.

These controls constrain abuse; they do not promise no unsolicited mail. Someone can still request a limited verification message for an address they do not own, aliases can reach the same physical inbox, and attackers can exhaust shared anonymous/bootstrap or delivery allowances. Distinct addresses are never merged into an account by guessing aliases. Conservative global caps remain necessary; trusted visitor attribution, monitoring, appropriate bot challenges and measured fairness/capacity remain release work. Raising volume requires reviewing these bounds. Password and mail flags stay disabled until the complete browser journey and activation gates pass.

## User and AI content remains data

The SQL validator already rejects multiple statements, writes, unapproved functions/relations and hidden data. This review closes additional parser paths: explicit custom operators and user-defined cast targets could bypass the function-node policy, while object-identifier casts could resolve internal catalog metadata. Those paths now fail closed. Explicit reviewed catalog primitives and ordinary permitted analytical operators/casts still work. Both the AST policy and restricted database role remain required; this does not claim that attacker-defined objects exist in the hosted database.

The answer renderer now exposes only a fixed formatting allowlist. Raw HTML is discarded, code fences render as text, Markdown images cannot create image/preload requests, and generated links are inert text, including relative API URLs. User/model content cannot install plugins, renderers, event handlers, iframes or executable chart options. Tables, SQL and errors continue to render through React text nodes. Existing authorized app JavaScript and the reviewed Google sign-in library are executable application dependencies; this is a boundary on untrusted content, not a promise that the site runs no code.

“Copy table” previously bypassed CSV's formula guard. Clipboard serialization now neutralizes formula-like text and headers, prevents embedded controls/tabs/newlines from creating additional cells and preserves genuine negative numeric values. CSV uses the same strengthened significant-prefix rule. The application does not execute exported data; spreadsheet consumers still differ, so representative supported spreadsheet/browser journeys remain a release check.

No user-controlled Python/shell evaluation, unsafe deserialization or arbitrary URL/file interface was found in the reviewed current request paths. Operator-configured providers are separate from submitted model identifiers. Future Plotly configurations, Settings imports, rich text, uploads and AI tools must preserve explicit data schemas and server-side permissions. P07 global AI admission/deadlines/result bounds and P05/P08/P09/P13 browser/feature/CSP/release gates remain necessary; this review does not mark unimplemented surfaces complete.

## Evidence and release status

The paired probes and final isolated candidate results are in [evidence/p04](evidence/p04). Recipient-spam red tests exercise the previous image against synthetic mail only; parser red probes never execute server code. Offline template and real ReactMarkdown rendering tests use fixture values and fake transports. Browser evidence, when recorded, uses a private local fixture with external requests intercepted before navigation. No real delivery or production flood is performed.

The final candidate is accepted only after its complete earlier regression matrix, new attack cases, legitimate recovery, packaged-source checks, migration/restore and code-quality gates pass. Initial failures are retained with their fixes and paired retests. Changes remain uncommitted on `codex/p04-password-access`, with password/signup/mail flags and the explicit worker inactive. See the current counts and image hashes in [P04.md](P04.md). Public launch and zero-risk claims are not implied.

Reference guidance reviewed October 20, 2026: [OWASP account recovery](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html), [OWASP XSS prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html). Per-recipient workflow limits and safe output handling complement server-side authorization; keyword filtering alone is insufficient.
