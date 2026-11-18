# Explicit user-saved context notes — HTTP/lifecycle contract

Candidate source only. Default `CONTEXT_NOTES_ENABLED=false`; production remains schema8. This slice needs migration0010 after the original schema9/P11 gates. It performs private application storage operations only: **no provider, business query, retrieval, automatic memory, training or analysis execution**. Existing preferences, saved prompts, help and result-brief DTOs are unchanged.

## Operator configuration

On an approved installation with private application storage enabled, verify schema 10 through the private readiness check after migration 0010. Keep the original P11 migration and recovery gates in force. Set `CONTEXT_NOTES_ENABLED=true` in the repository's gitignored `.env`. The backend service reads this file at container creation. The private storage overlay also loads `runtime.env` after `.env`, so keep the notes flag in one place. The flag accepts only lowercase `true` and `false`.

Recreate the backend through the installation's reviewed Compose configuration after setting the flag. No frontend build is needed. Sign in with a synthetic account that has a current dataset grant and open **Aqua tools → Saved notes**. Create a note, reopen it, select **Prepare**, review the draft, and apply it to the composer. Sending is a separate user action. To pause the feature, set the flag to `false` and recreate the backend with the same configuration. Saved rows remain subject to the usual account deletion and private export policies.

## Authority and limits

Only the fresh authenticated owner may act. The server derives the configured dataset and exact current durable grant version; client text/IDs supply no authority. A scope ID is a server SHA256 binding of owner/current dataset/grant version/auth epoch/history generation, not a bearer token. No raw dataset key, grant row, DSN or session identifier leaves this API.

Every response is <=32KiB; service work has a2s cooperative deadline and existing separately committed60/account/minute workspace admission. Mutations are strict UTF8 JSON <=8KiB, no BOM/NUL/duplicate/unknown keys or query fields. JSON integers are strict, never booleans. UUIDs use canonical lowercase form. Strings are plain text, never HTML, formula/SQL/configuration or trusted units.

Label:1–120 Unicode code points, <=512UTF8 bytes, single-line, no control/format characters, Unicode line/paragraph separators (Zl/Zp, U+2028/U+2029), or leading/trailing whitespace. Body:nonblank, <=2000 UTF16 code units AND <=2048UTF8 bytes; allow tab/LF only among control characters, reject CR, DEL/C1 controls, lone surrogates and all Unicode format (Cf) characters including bidi controls/zero-width format characters. Labels use the same Cc/Cf/Cs rejection without tab/LF, plus Zl/Zp rejection; body line/paragraph separators are preserved. Preserve authored bytes: no normalization or trimming. Kinds: `note|metric_definition`; both are unverified user statements.20 active notes/owner across all scopes;200 total retained rows/owner and5000 globally, including scrubbed tombstones. Existing16MiB/owner and200MiB/global workspace content caps remain unchanged.

## Closed JSON shapes

Common envelope fields on every successful response:

```json
{"schemaVersion":1,"owner_id":"canonical UUID","scope":{"id":"64 lowercase hex","can_use":true},"unverified":true,"execution_enabled":false}
```

`execution_enabled:false` means no analytical/model/action execution, not that private CRUD did not occur. `can_use` is a fresh advisory projection; it does not authorize a later operation.

Available metadata item has exactly:
`{id,revision,availability:"available",label,kind,created_at,updated_at}`.
Unavailable metadata uses the SAME keys, but `availability:"unavailable"`, label exactly `"Unavailable saved context"`, and kind/created_at/updated_at are null. Only its owner can see ID/revision; it exposes no old label/body/scope/time. Revisions are integers1..9007199254740991; times are timezone-aware ISO strings.

An available full note has exactly:
`{id,revision,kind,label,body,created_at,updated_at}`.

- **GET /api/v1/me/context-notes**: no query/body. Common envelope plus `items:[metadata]` and `limits:{active_notes:20,label_characters:120,label_bytes:512,body_utf16_units:2000,body_bytes:2048,draft_utf16_units:2000,draft_bytes:8000}`. At most20 active metadata items, newest updated_at/id first; no bodies. Current exact-grant rows are available. All other owned active rows are generic unavailable metadata. This listing and forgetting remain possible without a grant.
- **GET /api/v1/me/context-notes/{id}**: no query/body. Fresh current grant plus exact stored dataset/grant binding required. Common envelope plus `note:<full note>`. Foreign/missing/deleted/old-scope rows give generic404; no old body is returned.
- **POST /api/v1/me/context-notes**: exact body `{schemaVersion:1,client_request_id:UUID,expected_scope_id:hex,kind,label,body}`.201 on creation;200 only for an identical owned idempotency replay in the SAME current dataset/grant. Common envelope plus `note`. Reusing a key with different payload/scope is409; deleting it does not make the key reusable.
- **PATCH /api/v1/me/context-notes/{id}**: exact FULL snapshot `{schemaVersion:1,expected_scope_id:hex,revision,kind,label,body}`. Fresh exact current grant and CAS required; increments revision once, returns200 common envelope plus `note`. No partial patch/owner/scope transfer.
- **POST /api/v1/me/context-notes/{id}/forget**: exact body `{schemaVersion:1,expected_scope_id:hex,revision}`. Owner-only; works for unavailable metadata with the fresh list scope ID, even without a data grant. Scrubs label/body/fingerprint, refunds text storage, increments revision and retains a bounded tombstone/idempotency key.200 common envelope plus `deleted:{id,revision}`; no deleted text. Deleted/missing/foreign ID is404.
- **POST /api/v1/me/context-notes/{id}/prepare**: exact body `{schemaVersion:1,expected_scope_id:hex,revision}`. Fresh exact current grant/CAS required.200 common envelope plus `source:{id,revision,kind,label},draft:<EXACT body text>,requires_review:true`. Read-only apart from admission. Draft fits the unchanged existing2000-UTF16-unit/8000-byte composer limits and its tab/LF-only control policy. No SQL/model/memory injection, usage counter or chat write.

All six routes require captured `X-Aqua-History-Revision` once history generation exceeds1, including GET reads; mutations/prepare retain the existing compatibility rule at generation1. New history generation cannot silently adopt an old intent. Scope mismatch409 `scope_changed`; stale item revision409 `revision_conflict`; idempotency mismatch409 `idempotency_conflict`. Other fixed errors:401 session_invalid,403 access_denied,404 not_found,413/422 invalid_request,429 rate_limited/capacity_reached,503 service_unavailable. Disabled feature404. No raw error/input reflection. Existing private no-store/history/Vary headers and private logging suppression apply.

## UI/retention rules

Flow is explicit library selection -> fresh prepare -> review/edit composer -> separate Send. Bind owner/CSRF/history/scope/item/revision and unchanged target draft across async work; no automatic mutation retry or stale-draft overwrite. Changing users/history/grants closes or invalidates held state. Never store note bodies in localStorage or an extra result cache. Definitions are labeled user-saved/unverified; they cannot alter deterministic result facts/units.

Correct/forget advances privacy_epoch under the canonical existing user lock, invalidating prior staged exports. No plaintext edit-history table or body logging. Clearing chat history retains this deliberately saved library but invalidates held reads/writes; preference reset does not erase it. Once a user separately sends a draft, its text is ordinary message content: forgetting the library entry does not erase those message copies. Existing history/account deletion handles messages. No new bulk-reset/retirement scope is introduced here.

Account deletion must boundedly purge/refund notes from ALL old grants/scopes before user removal, including restore/replay. No new authority fields/fingerprint kinds. Migration/new table must be admitted by exact private-row/catalog/full-restore inventories and new image/source qualification; original migration bytes/native baselines remain intact.

## Export format decision (root approved)

NEW downloaded export documents use **schemaVersion2**, retain authority scope `personal_v1`, and add exactly one `context_notes` array. HTTP job/proof DTOs, proof target/digests, other section serializers and old ready v1 bytes remain unchanged. The scope identifies existing personal-data authority, not document-format version.

Available active notes export `{id,revision,availability:"available",kind,label,body,created_at,updated_at}` ONLY for the exact currently allowed dataset/grant. Other owned active notes export only `{id,revision,availability:"unavailable"}`. No old labels, bodies, timestamps or scope keys. At most20 entries; overflow fails, never truncates.

Any available note marks the existing internal scoped-sensitive predicate (`contains_results`) true, even with no result messages. Snapshot/publication/download must recheck its exact grant as they do protected result content. Correction/forget privacy_epoch changes invalidate staged output. New2/old1 immutable download, notes-only revoke/regrant, section equivalence, bounded purge and actual isolated restore require explicit tests. No production migration or activation is authorized by this document.
