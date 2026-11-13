# Prepared analysis and hybrid retrieval — opt-in source

Ben requested a review of the GH Logistics repositories' local-AI patterns and
bookkeeping-style preparation, with better speed/quality and preserved security.
The November 13 review inventoried all local Git checkouts under `Desktop/GH_Repo`
read-only, using the workstream registry and preflight. Some shared checkouts
are older feature branches; this was not a claim that every repository or live
service was refreshed. No shared checkout, company service, corpus or model was
changed. Detailed local source identities stay in the task's verification record.

## Implemented first slice

1. Optional hybrid schema retrieval combines BM25 identifier matching with the
   existing semantic ranking through reciprocal rank fusion. This helps an
   explicit table/column identifier missed by the top semantic candidates.
   `RETRIEVAL_HYBRID_ENABLED=false` is the default until held-out evaluation.
   It still makes the same one embedding call and two retrieval lookups, keeps
   four table candidates and the existing bounded join expansion, and validates
   worked SQL examples exactly as before. Empty/unauthorized indexes retain
   their existing availability/deny behavior. An unauthorized vector hit is
   denied before fusion; it cannot disappear behind authorized lexical hits.
2. The lexical pass uses only the current job's approved table/column names.
   It reads no sampled values, comments, result rows, other accounts' history or
   company document content. Preparation is request-local, capped at 2,048
   tables, 256 columns/table, 512 terms/table and 32 question terms. No query
   history or embedding cache is shared across users.
3. `python -m eval.knowledge_pack` prepares reviewed analysis recipes for the
   existing worked-example indexer. Its source-byte SHA must match what the
   operator reviewed. The dataset ID and table-allowlist digest must match the
   selected scope, every example must be training-only, and each SELECT must
   use exactly its declared approved relations. Ambiguous fields, writes,
   foreign tables, holdout examples and unreviewed packs are rejected.
   Default is a count/hash-only dry-run; an explicit output is create-only.
   Compilation makes no network, database, model-training or embedding call.
4. `python -m eval.compare_runs DATASET BASELINE CANDIDATE` compares complete,
   identical held-out case sets from the existing evaluator. It rejects missing,
   duplicate, training-only and modified gold cases, invalid timings and fake
   success records. Outages stay in the accuracy denominator. Its default gate
   requires no aggregate accuracy/outage regression and at most 1.2 times the
   baseline p95 latency, with at least 20 test cases. Reports contain aggregate
   metrics and file digests, never questions, SQL or result rows. Seven offline
   guard tests cover these boundaries. Passing this gate alone does not authorize
   production activation, prove statistical significance or attest the inputs.

The review digest is a binding to reviewed bytes, not a new authorization token
or proof of who reviewed them. Existing operator/indexer permissions and fresh
runtime owner/dataset/grant checks remain the authority. A prepared SQL example
is a pattern for analysis; it cannot post bookkeeping entries, change balances
or create a grant. The normal validator, read-only database role, worker limits,
120-second deadline and four-provider-call ceiling still apply.

This is retrieval and evaluation engineering, not a claim that new model weights
have been trained. The pack is prepared input for a separately authorized
indexing step. Its JSONL output does not itself carry a runtime grant or enforce
a database identity: the operator must retain the reviewed source/dataset
binding and select the matching database, and the existing indexer revalidates
SQL against that database's reader-visible schema. Do not use the indexer on the
live analytical database as part of this work.

## Preparing an analysis recipe

Create a private JSON object with exactly `schemaVersion: 1`, `approved: true`
after human review, the intended `dataset` identifier, `allowlist_sha256` from
`eval.knowledge_pack.allowlist_hash`, and an `examples` array. Each reviewed
example has `id`, `split: "train"`, `question`, `sql` and `tables`. Use read-only
report/reconciliation patterns, not instructions to an agent. Keep provenance
and review notes alongside the source outside the public repository.

With the backend dependencies/Python path active, dry-run:

```text
python -m eval.knowledge_pack PRIVATE_PACK.json --reviewed-sha256 REVIEWED_SHA256 --dataset DATASET_ID --tables account,loan
```

Only an explicit `--output NEW_PRIVATE_PATH.jsonl` creates an artifact. Retain
the source and output digests together. A candidate corpus and an evaluation
holdout are separate artifacts; do not promote the latter into the examples.
The existing indexer's `--dry-run --dataset NEW_PRIVATE_PATH.jsonl` is a later
operator action against the intended database; it needs separately configured
read-only/indexer roles and is not run automatically by the compiler.

## Applying the broader local-AI patterns

- Curate dataset-specific definitions and read-only report/reconciliation
  recipes with source/revision provenance. Treat missing knowledge as an
  explicit gap; promote reviewed examples separately from evaluation cases.
- Keep document permissions attached through chunking, indexing, retrieval,
  citations and deletion. Document text remains data, not agent instructions.
- Re-embed only changed, approved content. A local embedding adapter needs an
  explicitly versioned model/dimension/index namespace and a migration/eval
  gate; it must not silently reuse incompatible vectors.
- Evaluate the existing local models on the same held-out questions before
  changing routing, quantization or fallback. The inspected Aqua host already
  has local completion models; this work did not download weights or run an
  unbudgeted training job. Endpoint/model availability is not a quality result.
- Consider namespace-bound caching only where the cache key carries current
  owner, dataset, grant/auth/history revisions, model/prompt versions and
  freshness. The current worker Budget carries questions and a context digest,
  so an owner-scoped embedding cache requires an explicit scope extension.
- Keep tuning/distillation datasets reviewed, scoped, separated from holdouts
  and deletable. Synthetic or self-generated answers are candidates until
  reviewed; they do not automatically become ground truth or model weights.

The source systems' knowledge patterns are adapted here with synthetic examples.
Their business records, messages and pending-review Q&A were not imported into
the public Aqua repository, connected to Aqua users or sent to a model.

## Qualification limits

The 36 added pure/transport tests passed in the networkless pinned runtime.
The synthetic benchmark measures identifier recovery and CPU overhead only;
its intentionally missed vector targets do not measure real semantic retrieval,
end-to-end latency, financial correctness or model accuracy. Full retained
backend, exact native inventory/recovery and PR/main CI are still required for
the combined source. Both flags and the live schema8 release remain unchanged.

The final installed runtime was independently inventoried as
`sha256:dc50f945f9c20e5c064e4f89a7d83edc30ed75f9bf47018415d936f07171f044`:
197 compiled files, 200 app files and one dependency lock. Its disposable
installer/genesis recovery and ordinary-runtime flag-off purge, invalid-restored
startup denial and retained-authority recovery all passed with cleanup and zero
production mutations. See `evidence/ai/`. Encrypted independent retention and
total-host restore remain unproven release gates. The first full backend run
caught two new CLI tests depending on pytest's parent import path; their
entry-point/root-directory repair is under a fresh full run. Preserve that red
evidence; do not represent the partial run as passing. Consult the PR's exact
head and distinct main checks for the eventual integrated result.

Before enabling hybrid retrieval, compare held-out table recall, SQL/result
correctness, abstention, provider calls, p50/p95 latency and scope-denial cases
against the current baseline using the same authorized schema/model. Agree on
acceptance thresholds and regression limits before promotion. Follow the
[personal-computer release gates](PERSONAL_COMPUTER_RELEASE_HANDOFF.md).

Algorithm references: [BM25 IDF and defaults](https://lucene.apache.org/core/10_5_2/core/org/apache/lucene/search/similarities/BM25Similarity.html),
[rank fusion](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion).
