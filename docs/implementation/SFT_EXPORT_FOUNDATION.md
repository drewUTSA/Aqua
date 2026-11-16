# Reviewed SQL SFT export foundation

This prepares bounded artifacts for a possible future supervised fine-tuning
experiment. It does not train a model, generate a corpus, fetch a tokenizer,
download weights, install training packages, call a provider/database or certify
that enough suitable examples exist. It is separate from retrieval indexing,
the existing64-example knowledge compiler, and the local-model smoke harness.

Only reviewed Aqua-owned or publicly permitted SQL examples belong here.
Company/GH records, messages, personnel/freight data, private business corpora,
independent evaluation cases and automatic self-generated answers are excluded.
Rights and provenance are explicit declarations; their presence and hashes are
not independent attestation of ownership, license compatibility or review.

## Inputs and independent review bindings

The exporter accepts three private files, each requiring its own reviewed-byte
SHA256: an approved source envelope, a rendered production-schema snapshot and
a test-only independent holdout JSONL. The schema snapshot must be reviewed
against the intended dataset/table scope. Its byte hash binds the supplied
text; it does not prove that it originated from the production schema loader,
that a column exists or that any example executes correctly.

The source envelope has exactly `schemaVersion: 1`, `approved: true`, `dataset`,
`allowlist_sha256`, `schema_sha256`, `provenance` and `examples`.
`allowlist_sha256` uses the existing `eval.knowledge_pack.allowlist_hash` over
the intended tables. `schema_sha256` is the exact schema input-byte hash.

`provenance` has exactly these fields:

- `source_id`, `revision`, `license`: nonempty bounded declarations identifying
  the reviewed source and applicable rights; preserve the actual license and
  review evidence alongside the private source.
- `rights`: `aqua_owned` or `public_permitted`.
- `reviewed_for_sft`, `aqua_or_public_only`, `no_company_data` and
  `semantic_leakage_reviewed`: explicitly `true` after the corresponding review.

Each example retains the existing compiler fields: `id`, `split`, `question`,
`sql`, `tables`. The source contains2..64 examples total, with at least one
`train` and one `validation` entry. Source bytes remain capped at256KiB; other
question/SQL/table bounds and AST/table validation reuse the existing compiler.
Validation is an internal development partition, not the independent test set.

The independent holdout has test-only JSONL records with `id`, `split: "test"`,
`question` and `sql`. Existing optional `tables`, `difficulty` and `ordered`
fields and a bounded optional `rule` identifier are accepted. The 8MiB/2,000-case
bound is retained. It must be a separately
reviewed artifact, not a selection promoted automatically from this source.

IDs, NFKC/casefold/punctuation/whitespace-normalized questions and validated
canonical SQL must be unique across training/validation and disjoint from every
protected holdout record. Protected records retain unique IDs, but may repeat
question forms or canonical SQL; all records remain protected and counted. For
example, public Pagila test records t12/z14 both ask for the maximum replacement
cost and remain excluded. Equivalent SQL formatting/comments do not evade
exclusion. SQL alias rewrites, paraphrases,
near-duplicates and other semantic leakage still require independent human
review; canonicalization does not prove semantic independence. This exclusion
contract does not claim that repeated protected questions form statistically
independent evaluation cases.

## Dry-run and create-only export

From the application root, with the existing runtime dependencies available:

```text
python -m eval.sft_export REVIEWED_SOURCE.json REVIEWED_SCHEMA.sql INDEPENDENT_HOLDOUT.jsonl --source-reviewed-sha256 SOURCE_SHA256 --schema-reviewed-sha256 SCHEMA_SHA256 --holdout-reviewed-sha256 HOLDOUT_SHA256 --dataset DATASET_ID --tables account,loan
```

The default prints only counts/digests and performs no write. An explicit
`--output NEW_PRIVATE_DIRECTORY` creates `train.jsonl`, `validation.jsonl` and
`manifest.json` outside the application checkout. The parent must already exist;
the output directory and every file are create-only. An existing directory,
file or link is never overwritten. A partial failure retains an incomplete
directory without a final manifest; inspect it and select a new destination.
Use an appropriately private parent directory, especially on Windows where
POSIX creation modes do not establish a complete owner-only ACL policy.

Training records contain production system/user messages and assistant JSON
`{"sql":"..."}`. User prompts use the reviewed schema, production prompt
builder and answer-size policy. Ambient conversation history is cleared for
export and restored afterward; no account/session/private history is borrowed.
Original reviewed source/schema/holdout hashes remain distinct from deterministic
compiler-input conversion hashes. Re-labeling the internal validation partition
for the training-only structural compiler does not claim separately attested
human review of those converted bytes.

The manifest binds artifact, example, schema, source, provenance and production
generator/response-format digests. It contains no source question or SQL text.
It explicitly reports no execution-correctness verification, tokenization,
actual training, adequate-corpus claim or production-activation authority.

## Future model/trainer boundary

The declared base is `Qwen/Qwen3-4B`, revision
`1cfa9a7208912126459214e8b04321603b3df60c`, with declared Apache-2.0 license,
and non-thinking rendering (`enable_thinking=false`). This records the intended
base; it neither downloads nor verifies model/tokenizer bytes. The future
trainer must verify licenses/artifacts and apply that exact tokenizer/chat
template in non-thinking mode. Plain message JSONL is not tokenized training
data, an established training recipe or a trained personal companion.

Before training: acquire a sufficiently varied reviewed corpus, separately
verify SQL/result correctness, freeze leakage-reviewed train/development/test
splits, qualify the untuned baseline, pin trainer/tokenizer/dependencies and
hardware/resource budget, then evaluate a candidate adapter against the same
independent holdout and existing SQL security boundaries. No automatic history
ingestion, answer promotion, model-weight update or production routing change
is authorized by an export. P11/P12/P13 release gates remain unchanged.
