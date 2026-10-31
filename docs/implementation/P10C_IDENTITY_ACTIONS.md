# P10c identity actions — isolated implementation

This candidate exists only in `p10c-work`. P10a is deployed on schema 6; the
P10b base was copied while its canonical checks were pending. P10c is not
deployed or complete. No real Google verifier, mail recipient, analytical
provider, production database or Git operation is exercised by this work.

## Public contracts for the subsequent frontend integration

All routes below are under `/api/v1/me`. They require the current canonical
session. Every POST/PUT also requires exact configured Origin and that same
session's `X-CSRF-Token`; paired cookie-B/CSRF-A fails before SQL. Bodies are
strict, closed JSON, at most 16 KiB. Queries and duplicate JSON keys are denied.
Replies are private/no-store and errors use the existing safe error envelope.
No owner, verifier result, timestamp, digest or permission is accepted.

The existing password challenge/verification DTO adds `email_change` with
`new_email`, `google_link` without a target, and `google_unlink` with canonical
`target_identity_id`. Existing B operations and result shapes are preserved.
Password verification cannot issue a `password_add` proof. Email normalization
uses the existing version-1 ASCII case-insensitive policy without dot/plus
rewriting. Google `password_add` targets the server's current primary mailbox.

| Route | Closed request | Success |
| --- | --- | --- |
| POST `/reauth/google-challenges` | `{operation,identity_id,target_session_id?,target_identity_id?,new_email?}` | `{schemaVersion:1,challenge_id,challenge_token,expires_at,client_id,nonce}` |
| POST `/reauth/google` | Same operation target, plus `{challenge_id,challenge_token,credential}`; no `identity_id` | `{schemaVersion:1,proof_token,expires_at}` |
| POST `/google-link-challenges` | `{proof_token}` for `google_link` | Google challenge result above |
| POST `/google-link-candidates` | `{challenge_id,challenge_token,credential}` | `{schemaVersion:1,candidate_token,expires_at,google:{email}}` |
| POST `/google-links` | `{proof_token,candidate_token}` | `{schemaVersion:1,linked:true,current_session_revoked:true}` |
| POST `/methods/google/{identity_id}/revocations` | `{proof_token}` for that exact `google_unlink` target | `{schemaVersion:1,unlinked:true,current_session_revoked:true}` |
| POST `/password-enrollments` | `{proof_token}` for `password_add` | `{schemaVersion:1,request_id,request_token,expires_at,confirmation_required:"primary_email"}` |
| POST `/password` | `{proof_token,request_id,request_token,email_token,new_password}` | `{schemaVersion:1,password_added:true,current_session_revoked:true}` |
| POST `/email-change-requests` | `{proof_token,new_email}` | Mail request result with `confirmation_required:"old_and_new_email"` |
| PUT `/email` | `{proof_token,request_id,request_token,email_token,old_email_token}` | `{schemaVersion:1,email_changed:true,current_session_revoked:true}` |
| GET `/notification-settings` | No body | `{schemaVersion:1,user_id,revision,values:{in_app_success,preview},capabilities}` |
| PUT `/notification-settings` | `{expectedRevision,in_app_success,preview}` | Same snapshot; stale revision 409 |

`operation` is one of password_change, password_add, email_change, google_link,
google_unlink, session_revoke, sessions_revoke_all. Other-operation target fields
are prohibited. `identity_id` on the Google start is an owned active method UUID
from the methods DTO; server snapshots its exact revision. Public UUIDs are not
bearers. Proof/request/challenge/candidate tokens are `v2.` plus 43 URL-safe
characters; mail tokens are the existing 43-character unprefixed format.
Candidate email is provider-observed plain text for explicit confirmation, not
proof of app-primary ownership and never permission to merge accounts.
The methods DTO adds `email` to each owned Google identity alongside `id` and
`linked_at`: a sanitized string or null, at most 320 characters, for exact method
selection. It is a provider-observed label, never app-primary/mail-control proof.
Do not return issuer, subject, raw claims or the internal observed-email key.

Google proof challenges retain `__Host-aqua_account_action` (local HTTP name
`aqua_account_action`), Max-Age 300. Pending link/mail requests use a separate
`__Host-aqua_identity_action` (`aqua_identity_action` locally), Max-Age 300 for
link or 1800 for mailbox requests. Both are Path `/`, HttpOnly, SameSite=Lax,
Secure on HTTPS. Reauthentication can therefore refresh the former without
invalidating the pending mailbox request. A new pending request replaces its
own browser binding. Confirmed credential/method/email/current/all-session
changes clear cookies after commit and require ordinary sign-in; no new session
is minted. Errors preserve session cookies and action state unless the server
already consumed a one-use verifier challenge.

New email links use `/account-action/{purpose}#request=<public UUID>&token=...`; opening a link alone
changes nothing. The frontend must clear the fragment immediately, keep tokens
and passwords only in transient memory, and return them to the initiating
same-owner action. Do not broadcast bearer tokens or write them to device
storage. Cross-browser completion requires starting a new flow.
The initial supported handoff is explicit pasting of the original mail link
into the still-open initiating dialog. Validate exact configured origin, fixed
purpose, canonical request UUID, exact token format and no extra query/fragment
keys, then clear the uncontrolled input immediately and require a separate
Confirm action. Do not fetch pasted URLs or use programmatic clipboard access.
The public landing scrubs its fragment before UI/SDK work and explains returning
to the open Settings action. UUID possession does not recover the transient
request secret or imply automatic resume after reload/new-tab navigation.

## Security and resource invariants

Additive migration 0007 preserves applied 0001–0006, tombstones and grant
provenance. It adds Google revision snapshots, invalidates legacy Google proofs
instead of backfilling authority, binds pending requests/mail tickets, extends
closed purposes and stores notification settings separately from preferences.
Readiness/installer/fixtures must agree on schema 7. No startup migration occurs.

Google SDK verification runs without a DB lease after durable challenge claim.
Signature/audience/issuer/expiry, action-specific nonce and strict integer iat
are checked; iat must fit the challenge/server window with at most 30 seconds
clock skew and 300 seconds age. Final proof insertion rechecks exact active
issuer/subject/identity revision, session and epoch. Proof lifetime never exceeds
300 seconds or its challenge expiry. Fresh GIS identity assertion does not
claim MFA, a newly typed Google password, or a real-provider test.
Only after those checks and the final current-user/revision check does an owned
Google proof publish its normalized provider email/authoritativeness observation.
The existing grant policy then denies known contradictions to email-derived
approval at queries, saved-result delivery and open streams. This observation
does not change the app primary mailbox/profile or create, restore or rewrite
any grant; operator approval and existing revocations remain intact.

Linking proves an existing usable method and the new Google method independently,
then confirms once. Subject lock precedes user lock consistently with login.
An identity owned elsewhere conflicts without account merging. Unlink and
reactivation lock the identity row, revoke at most 20 live identity-derived grants
through the partial index and recheck provenance in the UPDATE; operator grants
and prior revocations are preserved. Re-link never seeds/revives approval.
Last usable method is checked under the user lock. Every method/credential/email
mutation advances epoch and revokes only the bounded 20 live current-epoch
sessions; retained expired history is not swept.

First password requires fresh Google proof and distinct primary-mail possession;
anonymous reset cannot create it. Email change requires both old and new mailbox
tokens and a fresh proof bound to the exact new target. No pending request
reserves an address or changes primary. Final completion preserves canonical
account/history and bumps email/profile revisions. Old addresses remain bounded
non-primary records and cannot be used for password login/reset. No inaccessible
old-mailbox recovery shortcut is introduced.

Action admission stays 5/account/minute and 30/global/minute. Ordinary Google
proof plus mutation costs three calls, link costs five, and mailbox flows cost
four if the original proof is still fresh. Mail requests expire in 30 minutes;
if delivery outlives the 300-second proof, the user explicitly reauthenticates
and may need normal cooldown. No automatic replay, quota reset or proof extension.
All hash work shares the existing two-slot cap and owns no DB lease.

Mail capacity precedes user/session/request/proof locks. Paired mail jobs reserve
two slots atomically. All new verification purposes share the old verification
group/recipient budget; all mandatory notices share the old notice group. Limits
remain 20/hour and 60/day globally, verification 5/20, reset 5/20, notices 10/20,
one attempt/second, three attempts and existing leases. Recipient verification
limits remain three/24h and 300-second cooldown across purpose rotation. Legacy
AAD, three-field and v1 templates remain compatible; new exact v2 templates
contain no private prompts/answers or credentials. Token-free security notices
are committed with the mutation, independent of optional notice consent and
challenge deletion; queued is not delivered.

## In-app notice contract and capabilities

Defaults are `in_app_success:false`, `preview:"generic"`; preview may be `hidden`.
Capability DTO is `{in_app:true,browser:false,email:false,sound:false,quiet_hours:false}`.
The frontend may render only fixed generic status for owned live transitions,
with bounded deduplication. Essential errors/expiry/save failures cannot be
suppressed. The settings endpoint uses independent CAS and the shared metadata
60/account/minute budget; imports/preferences/reset cannot subscribe or enable
it. Browser permission, sounds, optional email, quiet hours and marketing remain
unsupported. Profile capabilities add `in_app_notifications`; external
`notification_delivery` remains false. Never deploy the old strict decoder with
new capability keys; the subsequent C frontend is a separate required gate.

## Required verification and release gates

Implementation is under active review. No canonical, migration, browser or
release result is claimed from authored tests. Required gates include both
isolated datasets, independent Storage pools and races, original regression case
retention, SQL/role/index/migration checks, actual restored-clone proof/session/
request invalidation with preserved notification CAS and mandatory notice
obligations, grouped mail budgets/legacy retries, frontend units/builds, all
existing browser gates plus new real C journeys, and source/runtime-byte proofs.

Root owns future C canonical packaging, nginx/proxy CPU aliases and frontend
integration. Real release additionally needs current Google origin/audience
eligibility and matching encrypted mail/worker configuration, verified protected
backup/restore procedure and compatible schema-7 forward recovery. Public Google
audience, shared/Tiger DB, analytical grants and provider/mailbox tests are outside
this implementation authorization. P10 remains incomplete.
