# Saved-result companion contract v1

Local evidence and its limits are recorded in
[the November 17 qualification](RESULT_COMPANION_QUALIFICATION_20261117.md).

Source increment, default off under the existing typed `COMPANION_ENABLED` flag.
It reads a currently authorized saved result. No model, analytical query,
new persistence/memory, SQL execution, approval or bank authority is added.
Existing application-help DTOs/menu and the ten-module help package are unchanged.

| Caller / result | Read brief |
|---|---|
| Flag off | Fixed 404 |
| Missing/revoked session | Existing 401 |
| Current owner, current dataset/grant/history, successful durable reply | Allowed |
| No/revoked/old dataset grant | Existing 403 |
| Foreign/deleted/legacy job or unfinished/failed request | Fixed 404 |
| History/reset/restore mismatch | Existing history/admission denial |

POST `/api/v1/companion/result-brief`; no query parameters. Cookie, Origin/CSRF,
existing committed workspace allowance, current job authorization before/after
projection, two-second cooperative deadline and 32768-byte complete response cap.
The raw body is at most8192 bytes of UTF8 JSON. BOM, NUL, malformed UTF8,
duplicates/escaped duplicates and unknown fields are rejected on this route.
The existing help/raw-body defaults remain unchanged.

```json
{"schemaVersion":1,"request_id":"33333333-3333-4333-8333-333333333333","column_index":0}
```

All three keys are required. Version/index are strict integers (never booleans),
version is1, UUID is canonical lowercase, and index is0–63 and must exist in the
saved table. The browser sends no rows, SQL, owner, roles, source, unit or URL.

All success keys below are required/closed; no additional nested keys:

```typescript
type Reply = {
  schemaVersion:1; owner_id:UUID; chat_id:UUID; request_id:UUID;
  assistant_message_id:UUID; job_version:SafeIntegerAtLeast1;
  brief:{
    method:"saved_result_rules"; status:"ready"|"limited"; question:string;
    source:{id:Hex64|null;generated_at:ISOWithTimezone|null;freshness_at:null};
    scope:{basis:"returned_rows_only";truncated:boolean|null;max_rows:1000|null;
           filters:"unknown";aggregation:"unknown";
           precision:"sidecar_preferred"|"legacy_unverified"};
    field:{index:Integer0To63;key:string;label:string;
           kind:"numeric"|"text"|"boolean"|"mixed"|"empty";unit:null};
    counts:{returned_rows:Integer0To1000;missing_values:Integer0To1000;
            non_missing_values:Integer0To1000};
    numeric:null|{minimum:Extreme;maximum:Extreme};
    checks:{id:CheckId;text:string}[];
    followup_intents:("verify_scope"|"missing_values"|"compare_field")[];
    execution_enabled:false;
  };
};
type Extreme = {value:CanonicalNumericString;ties:Integer1To1000;
                witness_rows:Integer0To999[]};
```

Question: at most2000 characters/8000 UTF8 bytes; newline/tab are permitted.
Field key/label: nonempty, at most256 characters/1024 UTF8 bytes, no control
characters. Timestamps: timezone-aware ISO, at most40 characters. Numeric strings
have at most256 characters and match `-?(0|[1-9][0-9]*)(\.[0-9]+)?`; no scientific
notation, commas or currency formatting. Exact sidecar text is preserved.
Integers and integral floats outside JavaScript's safe integer range require a
valid exact sidecar pointer before numeric comparison; absence is a fixed503.

Counts partition the returned rows. `missing_values` counts actual nulls, never
the strings "null"/"NULL" or empty text. Numeric kind requires all non-null
selected values to be finite numeric JSON cells (booleans/strings excluded).
Mixed types do not receive partial numeric comparisons. Empty means zero
non-null values. Decimal comparisons add no float conversion/rounding.
Extrema describe only returned rows, with their full bounded tie count. Witness
indices are unique/ascending and contain the first at most3 matching rows.
Both extrema can have the same value. Each witness is the selected table field
at that row, not a person/account/entity identity.

For PostgreSQL `FETCH FIRST ... WITH TIES`, saved SQL preserves the requested
cutoff, ordering and offset. Aqua reads at most 1,001 rows from a forward-only
database cursor, returns at most 1,000, and marks the result truncated when it
observes the extra row. A tie group can span the application cap. An external
SQL client running the displayed statement applies its own return limit.

Ready requires a valid existing v1 `result_metadata` descriptor. Source ID and
generated time come from that saved descriptor; max_rows is1000; truncation is
its actual flag. Prefer/validate the exact-value sidecar. Numeric is present
only for ready numeric fields with at least one non-null value. Units remain
null in v1; legacy `type:currency`, names and renderer formatting are not unit
proof. Filters/aggregation/freshness remain unspecified. No sums, averages,
growth, causes, business ranking or invented period/completeness are calculated.

Limited means metadata is absent, not malformed. All three source fields are
null, scope truncation/max_rows are null, precision is `legacy_unverified` and
numeric is null (even if field kind is numeric). Counts and source field labels
can still describe the saved table. Malformed current metadata fails fixed503;
it is not silently downgraded. A limited result retains its normal table/export.

Checks are unique and occur in the following order, with exactly this text:

| ID | Condition | Text |
|---|---|---|
| returned_subset | truncated true | This result is truncated. These checks cover only the returned rows; ask for an aggregate/count or narrower scope before treating the list as complete. |
| missing_values | missing_values >0 | Some returned rows have no value in this field. Decide whether missing values should be excluded or shown separately before comparing. |
| units_unknown | Always | The field unit is unspecified. Confirm its definition and unit before using it for a financial comparison. |
| freshness_unknown | Always | Source freshness is unavailable. The saved generation time does not establish how current the source data is. |
| scope_unknown | Always | Filters and aggregation are unspecified. Review the original question and SQL before assuming what one returned row represents. |
| precision_unverified | Limited | This older saved result has no verified precision descriptor. Numeric extrema are unavailable; use its existing table and verify important figures against the source. |

Follow-up IDs are unique/in this order: `verify_scope` always,
`missing_values` iff that count is positive, and `compare_field` iff ready numeric
comparison is present. At most3 IDs and6 checks; check text is at most512 UTF8
bytes. These are inert UI intents, not tool permissions, preapproved prompts or
executors. The UI reuses the existing guided-question serializer and editable
fields, leaving unknown grouping/period/filters explicit. It must not claim that
an arbitrarily old selected result's exact SQL/filters are anchored: existing
analysis context still selects at most8 earlier questions and2 successful SQLs.

The browser binds owner/chat/request/assistant message/selected field index+key
to its initiating currently authorized message. A historical message has no
job-version field; accept a fresh positive server version and fence by the
message/result/history binding (compare any available current analysis version).
Numeric witness equivalence can reuse `compareExactNumeric`; do not recompute
the extrema or round exact strings through `Number`. Close/selection/owner/token/
history/access changes invalidate pending/visible private state. No automatic
per-message request and no second cross-chat result cache.

Preparing and applying a follow-up causes zero analysis/provider calls. Applying
requires unchanged current owner/history/chat/selected message and composer draft;
conflicts preserve the draft. The user separately presses Send. Error/retry,
close and optional-chunk failure retain the workspace/table/composer.

Failures retain the existing fixed no-echo envelope:404 `not_found`,401
`session_invalid`,403 `access_denied`,409 history conflict,422 `invalid_request`,
413 raw-body cap,415 media,429 shared admission,503 unavailable/deadline. Private
headers/access-log suppression remain. No source rows/SQL or input diagnostics
are copied into errors or shared logs.
