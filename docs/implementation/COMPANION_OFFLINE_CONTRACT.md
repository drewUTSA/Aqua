# Offline companion qualification contract

`eval/companion.py` is an offline, pure-data qualification foundation. It has no
route, model, database, filesystem, environment, memory store or tool executor.
It does not enable companion features or train weights.

`assemble_context` takes bounded JSON bytes and explicit caller actor/scope
canonical UUIDs, bank/Pagila dataset, SHA-256 schema revision and integer UTC
epoch time. The envelope and every block must match those supplied bindings.
Schema version 1, explicit approval, unique artifact IDs, exact field sets,
valid UTF-8, at most 16 blocks and freshness of at most one hour are required.
Input is capped at 32 KiB and generated context at 16 KiB; no truncation occurs.

The four block kinds are reviewed Aqua help, dataset metadata (description and
table identifiers), owned question text, and an explicit subset of existing
allowlisted presentation preferences. Questions carry no SQL, rows or result
summaries. Preferences cannot supply instructions, permissions or model choices.
Generated JSON contains only the dataset/schema binding and projected artifact
data. Owner/scope, approval and freshness metadata stay outside generated prose;
auth/session/grant/secret and unknown fields are rejected, never copied.

**All approval, ownership, schema and availability declarations are caller
attestations, not authentication or authorization proof.** Text is marked
`untrusted_data`: approval never elevates prose to system instructions. This is
not a secret detector; a reviewer must exclude confidential information from
otherwise allowed text. No company corpus or live account data is bundled.

`validate_choices` accepts versioned JSON choices with only `capability_id` and
`artifact_id`. The caller must supply the same actor/scope/dataset/schema and
current time, the immutable assembled Context, available capability IDs and
authorized artifact IDs. Rewound/expired contexts fail. Capabilities and artifact
authorizations default empty. Only these offline vocabulary associations exist:

| Capability ID | Required artifact kind |
| --- | --- |
| `app_help` | `aqua_help` |
| `authorized_question` | `owned_question` |
| `monthly_trend` | `dataset_metadata` |

At most three distinct capability choices are allowed. Unknown/unavailable
capabilities, unknown/unapproved artifact references, mismatched kinds,
duplicates and extra URL/SQL/execution arguments fail closed. Successful output
always says `execution_enabled: false`; vocabulary membership makes no claim
that any capability is implemented or available in the application.

A future live adapter must derive bindings and current availability from the
server, select owned records under current grants, rebuild fresh context, and
reauthorize each action immediately before execution. Existing question budgets,
SQL AST validation and read-only execution remain independent requirements.
Synthetic tests in `backend/tests/test_companion.py` cover this offline contract;
they establish no model quality, trend accuracy, live authorization or training.
