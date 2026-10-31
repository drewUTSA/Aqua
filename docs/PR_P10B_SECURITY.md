# Phase10 Security

Require fresh current-password verification and a separate confirmation before
changing a password or ending the current, another, or all sessions. Proofs are
single-use and bound to the account, session, action, target and credential;
password changes atomically revoke sessions and queue the mandatory encrypted
security notice. Existing quotas, hash capacity and private storage boundaries
remain in force. Google-only password addition and identity changes remain
unavailable in this slice.

The account UI follows server capabilities, clears transient credentials and
proofs on authority changes, and reconciles uncertain responses without replaying
a mutation. Native sensitive-action dialogs focus Cancel after opening. The
simplified homepage, Settings drafts and both UI shells are retained.

This follow-up pins `pyasn1` to the reviewed security update and preserves the
mail cleanup lock order. The Plotly browser check waits for the existing failure
banner to render before asserting the same chart and failure state.
Browser checks classify cloud-backed files with `lstat` while retaining link,
resolved-path, size and full-byte checks.

Validation required before publication:

- 1,519 backend cases across both disposable datasets; all 1,440 P10a and
  all 1,516 previous P10b test identities retained, with three additional
  cleanup regression cases.
- 492 frontend tests, both production builds, zero runtime dependency findings,
  all 22 fresh browser gates, and 62 fresh screenshots reviewed by root.
- Source/lock/format/lint/runtime-byte, privacy, telemetry, actual synthetic
  dump/restore, storage, rate-limit/proxy and absence-confirmed cleanup checks.
- Secure-context browser scenarios use a reserved HTTPS origin fulfilled through
  CDP, fake encrypted mail and isolated real APIs. They make no real-provider,
  inbox-delivery or DNS/TCP/TLS claim.

No migration: schema 6 and all six applied migration bytes remain unchanged.
Release requires both exact frontend-image proxy checks plus all three jobs in
PR and merged-main CI. The compatible P10a image pair can be restored without
restoring the database or reversing credential changes and revocations.

This PR also records the verified P10a deployment and protected encrypted backup.
P10 remains incomplete; identity actions and later phases are separate work.
