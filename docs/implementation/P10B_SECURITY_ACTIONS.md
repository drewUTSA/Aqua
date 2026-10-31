# P10b password proof and session actions — isolated candidate

This slice is implemented only in `p10b-work`, based on the frozen P10a account
foundation. It is not a production deployment, applied migration, complete P10
phase, live provider/mailbox test or a claim of frontend completion. Schema 6
and migrations 0001–0006 are unchanged. Existing wildcard account COPY and
`.dockerignore` rules already include the new modules; no dependency was added.

## Public contract for frontend integration

Every route below is under `/api/v1/me`, requires the current canonical session,
exact configured Origin and `X-CSRF-Token`, JSON content type and no query
arguments. Bodies are closed and capped at 16 KiB before parsing; unknown keys,
duplicate/escaped-duplicate keys and malformed JSON are rejected. All responses
are private `no-store`. No route accepts an owner, permission, method claim,
credential hash, expiry, authentication timestamp or caller-selected target
digest. No analytical dataset grant is needed.

| Route | Closed body | Confirmed HTTP 200 result |
| --- | --- | --- |
| `POST /reauth-challenges` | `{operation,target_session_id?}` | `{schemaVersion:1,challenge_id,challenge_token,expires_at,methods:["password"]}` |
| `POST /reauth/password` | `{operation,target_session_id?,challenge_id,challenge_token,password}` | `{schemaVersion:1,proof_token,expires_at}` |
| `PUT /password` | `{proof_token,new_password}` | `{schemaVersion:1,password_changed:true,current_session_revoked:true}` |
| `POST /sessions/{session_id}/revocations` | `{proof_token}` | `{schemaVersion:1,revoked:true,current_session_revoked:boolean}` |
| `POST /session-revocations` | `{proof_token}` | `{schemaVersion:1,revoked:true,current_session_revoked:true}` |

`operation` is exactly `password_change`, `session_revoke` or
`sessions_revoke_all`. `target_session_id` must be a canonical lowercase UUID
for `session_revoke`; it is omitted or null for the other operations. Public
session/challenge UUIDs are identifiers, never bearer credentials. Challenge and
proof tokens are independent random `v2.` plus 43 URL-safe characters. Dates
are server ISO instants. Requests do not include `schemaVersion`.

Challenge creation also sets `__Host-aqua_account_action` on HTTPS, or
`aqua_account_action` for supported local HTTP: Path `/`, HttpOnly, SameSite=Lax,
Secure on HTTPS and Max-Age 300. This independent browser-binding cookie is
sent by ordinary same-origin fetch and never read by JavaScript. Creating a new
challenge replaces this one browser binding, so another pending challenge can
become unusable. The server fails closed instead of silently rebinding it.
The cookie can remain until expiry/new challenge/current-session clearing;
successful proof consumption does not require JavaScript access to it.

After confirmed password change, revoke-all or revoking the initiating session,
the server clears the current session/login/action cookies only after durable
commit. The user returns to ordinary sign-in; no replacement session is minted.
Revoking another session preserves the initiating session. Existing confirmed
current-session sign-out retains its independent `/api/auth/logout` facade.

Errors use `{error:{code,message,request_id}}` with fixed safe text: 401 for
stale session authority, 403 `proof_invalid`/`method_unavailable`, 404 for an
unavailable owned target, 422 for invalid DTO/policy/query, 429 with bounded
Retry-After, and 503 for storage/hash/mail/service failure. Never reflect a
password, proof, mailbox, provider exception or private SQL in errors/logs.

## Conditional capabilities and unsupported actions

Profile and method DTO capabilities retain P10a keys plus `password_add:false`.
`recent_proof`, `session_revoke` and `sessions_revoke_all` are true only for an
account with an existing password credential while `PASSWORD_AUTH_ENABLED` is
true. `password_change` additionally requires enabled, valid encrypted account
mail configuration with the exact application origin; transient capacity can
still reject the mutation. Session-list `revoke_one` and `revoke_all` reflect
the same conditional revocation availability. Registration/recovery issuance
flags do not become gates for these existing-account actions.

The P10a frontend's constant capability decoder must be updated in the separate
P10b frontend integration. Never deploy a mixed old-decoder/new-backend pair or
claim a hidden/disabled button is backend authorization. The broader P09
`account_security` preference capability remains false.

First-password addition, Google proof, linking/unlinking, email change and
optional notification delivery remain unavailable. A Google-only account
cannot add its first password through reset, registration or these endpoints.
The handoff requires recent Google proof plus verified control of the address
used for local login; that is P10c work. No MFA/passkey, permission, primary
email, signup, grant or provider-configuration change is included.

Schema 6 stores a Google proof's identity ID but not its identity revision.
P10b therefore rejects Google proofs even through the shared low-level
`consume_proof(method=None)` primitive. Deactivating/reactivating a tombstone
cannot make one usable again. P10c must add an immutable identity-revision
snapshot through a reviewed additive migration and implement complete fresh
Google verification before enabling that branch. Existing identity tombstones,
canonical Google primary/profile authority and derived-grant fences remain.

## Recent-auth authority and resource bounds

The challenge is bound to current owner, exact session, auth epoch, finite
operation, canonical server-computed target digest, random secret and browser
binding. Claim and durable admission commit before password work. Wrong
password, hash-capacity denial or verifier failure cannot retry a successfully
claimed challenge. A mismatch cannot consume an unrelated challenge, but still
spends its authenticated claim admission. A new attempt needs a new challenge.

Password verification uses the existing login normalization with
`establish=False`, the reviewed `PasswordHasher.verify`, local semaphore and
durable `hash_slot`. It never calls ordinary password login or interprets
`authenticated_at` as proof. Argon2 holds no database lease. After verification,
the issuing transaction rechecks current owner/session/epoch, exact credential
hash/changed-at/primary snapshot, claimed challenge/action/target and expiry.
Only then can it insert a digest-only password proof. Its expiry is no later
than the original challenge and at most 300 seconds from issuance. There is no
public verified flag or general mint endpoint.

Creation, claim and each sensitive mutation separately commit the existing
shared action allowance: **5/account/minute and 30/global/minute** across
cookies/processes. Challenge creation commits its single charge before password
eligibility lookup; an authenticated Google-only refusal still spends that
allowance without allocating a challenge, proof or hash job. New cookies cannot
refill it. A normal complete action costs three admissions. A second
action may need cooldown; browser checks must not relax these policies to fit
several actions into one journey. Metadata/preferences retain their independent
shared 60/account/minute budget. Challenges retain at most five/account and
1024 total, with bounded cleanup and no eviction of live tombstones. Hash work
shares the established two-job local/durable cap with login/reset. Stale hash
slots fail closed until reviewed stopped-worker recovery; no timer evicts them.

The nginx challenge path shares the unchanged bootstrap zone (10/minute,
burst5). All four proof/mutation paths share the unchanged password-proof zone
(5/minute, burst3). Normalized escaped/trailing/repeated-slash aliases spend
those same budgets. All `/api/v1/me` access logs are disabled and profile/session
metadata stays outside CPU admission. The proxy exercise remains at most 120
requests, 5/second, four callers and 55 seconds with a fake upstream only.

## Atomic sensitive mutations

New-password establishment uses the existing NFC, 15–128 code-point, 512-byte,
blocklist policy without truncation. A cheap non-consuming proof precheck
precedes detached hashing; it cannot authorize the final mutation. Consumption
is repeated in the same short transaction as the actual mutation.

The password transaction takes mail-admission lock first, then user, session,
challenge and proof. Existing reset already uses mail-before-user; reversing
that order could deadlock. It consumes the exact password proof, rechecks the
credential snapshot after hashing, updates the credential and changed-at,
advances epoch, revokes the bounded live session set, invalidates currently
usable reset tickets and queues the mandatory encrypted `password_changed`
notice together. Any failure rolls everything back, including proof use and
cookie clearing. It reuses the fixed existing template and worker policy; a
queued notice is not a claim of inbox delivery and optional notice preferences
cannot disable it. No provider secret/network work enters the web action.

Revoke-one consumes proof for the exact owned live session UUID. Revoke-all
advances epoch and reads at most 21 current-epoch live session IDs; unexpected
excess above 20 fails closed. It updates only the at-most-20 explicit IDs, never
retained expired session history. Epoch mismatch invalidates copied historical
cookies without a history sweep. User locks serialize concurrent login/reset/
security changes; existing query/result/stream authority checks still apply.

Reset cleanup uses the existing `challenges_password_target` live partial
index, exact current primary/owner/epoch and captured expiry instant. It reads
at most four tickets and fails closed above three, matching the established
three-link/day recipient ceiling and 30-minute reset lifetime. Matching reset
mail IDs are likewise capped at three. Only those explicit UUIDs are touched;
expired/older-epoch history remains and denies by the new epoch. No applied SQL
migration or checksum was edited to obtain these bounds.

## Frontend failure behavior required next

Use explicit action-specific confirmation. Hold passwords/challenges/proofs only
in transient owner-scoped memory; never preferences, exports, device storage,
URLs or analytics. Clear current password after each attempt. Disable duplicate
submission but retain server one-use and concurrency enforcement. Abort/discard
stale results on owner/auth changes, suppress private top-layer dialogs while
the workspace is hidden/inert, and do not save account operations through the
ordinary preference save/import/reset controls.

The existing session-CSRF pairing also fences a cookie switch before a
cross-tab event arrives: an old owner's captured CSRF paired with a new owner's
cookie rejects before session authentication SQL, challenge admission or hashing.
Owner and CSRF must remain one atomic authenticated-state snapshot in the UI.
An explicit five-route/two-account regression forbids any SQL on that mismatch;
no caller-selected owner field or weaker ownership substitute was introduced.

Lost responses remain uncertain. Do not automatically replay a mutation or
claimed challenge. An explicit session-list/auth check may establish current
authority; an ended session alone is not proof that every intended change
completed. Reauthenticate/recover through the ordinary paths when needed.
Revoke-other can reconcile against a fresh owned session list. Preserve honest
failure/confirmation wording and the current-session sign-out behavior.

## Verification state

The dedicated browser bridge is `tools/checks/p10b_browser_backend.py`, accepts
only `https://aqua-browser.example.test` and an immutable image, and retains
network-none private resources, 300-second/300-operation host bounds and the
browser's 150-second deadline. Its opt-in worker flag is keyword-only and false
by default, preserving older HTTP fixture modes. Chrome CDP must fulfill every
static/API request at this reserved origin; this is no DNS/socket/TLS transport
or public-origin claim. The real application Origin, Secure/Host cookie and
CSRF processing remains unchanged, with a valid matching HTTPS fake mail policy
and a newly generated fixture encryption key. Production policy is not relaxed.

This fixture rejects rate/clock recovery, grant and fake-job controls and question
submissions. Use a fresh fixture for each sensitive-action scenario instead of
relaxing the five-action budget. Normal synthetic registration/verification/
password-login provides its starting account. `security_mail_status` exposes
only fixed `password_changed` purpose and bounded queued/completed/failed counts;
the security notice body/token mailbox path is denied. No real mail is sent.

Authored checks include real Argon2 success; closed/oversized/ambiguous bodies;
owner/session/CSRF/target/epoch/binding/method/expiry failures; copied/replayed
proofs; wrong-password and saturation recovery; independent-storage claim,
password/reset and revocation races; detached-work credential changes; mandatory
mail/DB rollback; bounded large expired session/reset history and unexpected
live excess; Google-only challenge refusals exhausting the default account/global
budgets; proof/challenge expiry during detached new-password hashing; Google-proof
denial after reactivation; safe errors and notices.

Locally executed: five closed action-contract methods, five account-policy
methods and 38 offline fixture-harness methods passed (cleanup12, startup7,
routes6, P08 boundary5, P10b boundary8). Source AST and source-policy checks
passed. These use no live application, DB, Docker, provider or network.
Full Linux formatting/lint, both fixture
matrices, proxy, runtime-byte, storage/restore and new frontend/browser gates
remain required. Exact local results and changed paths belong under
`.check-results/p10b`; no unexecuted DB/browser test is claimed as PASS.

The first canonical backend attempt found a new test-fixture name shadowing
the existing P07 security fixture, an over-budget test login setup, and a full
mail-queue seed missing its required UUID. The isolated test setup now uses
`account_security`, five genuine cookies plus one repeat, and an explicit mail
row UUID. These are test-only corrections; the complete canonical matrix must
be rerun before the candidate is accepted.

P10a schema-6 production prerequisites still apply. There is no production
migration, backup, restore, deployment, Git or real provider/mailbox operation in
this implementation. A matching encrypted backup/recovery plan, release review
and schema-compatible forward fix remain operator gates. P10c and the final P10
checkpoint remain outstanding.
