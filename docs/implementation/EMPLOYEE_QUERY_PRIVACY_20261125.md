# Employee query privacy

Ben requested both protections on November 25: employees see their own answers
without generated SQL, and cannot see another employee's questions, answers or
requester identity. This supersedes earlier SQL-inspection product copy.

The delivery boundary projects authorized current and previous-source answers,
request snapshots, replays and the legacy query response. The `sql` compatibility
field is always empty. The private stored execution record remains unchanged for
validation, follow-up context and authorized operations. No public SQL-inspection
or administrator bypass endpoint is added.

Personal export creation projects an empty SQL field and its fragment validator
rejects nonempty statements. Answer rows and exact JSON number tokens retain
their existing representation. The UI removes SQL disclosure/copy controls and
discards statements even when an older response supplies them. Saved-ranking
review uses a bounded server-authored form hint; it still requires an explicit
tie choice and Send, and unsupported populations remain unfilled.

Owner and dataset authorization precede answer projection. Lists, saved history,
request polling and previous-source access retain their owner predicates and
generic foreign-ID denial. Export proofs, grant checks, expiry and physical
download guards remain required.

## Release admission

The source requires both layouts, actual session/API/browser checks, export
precision and cross-account checks, ordinary analytical regression, source/image
binding and the existing recovery/CI gates before public activation.

Older ready export attachments can contain SQL. Under the release's stopped
writers and export workers, verify that those attachments have expired or revoke
them with the supported export lifecycle, then capture and verify the resulting
state. Never rewrite their signed payloads or silently relax download checks.
Capture the updated release backup before reopening. An older backup restored
for use with this release needs the same export admission check.

The public fallback must enforce the same privacy contract. Until a compatible
fallback has qualified, keep the origin in maintenance on failure; do not reopen
an older SQL-revealing application. Previously downloaded employee files cannot
be retracted by a website update.
