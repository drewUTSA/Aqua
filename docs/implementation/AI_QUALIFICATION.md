# AI qualification tooling — November 16, 2026

This slice improves measurement of the existing retrieval implementation. It
does not change the production pipeline, deploy schema9, enable hybrid search,
train a model, or import company content.

## Evaluator changes

`eval/run_eval.py` now starts a fresh production `Budget` for each case before
gold execution: 120 seconds and four shared provider calls. The previous
context is restored after each case. These are cooperative pipeline controls,
not a claim that the standalone CLI has the production worker's OS containment.

Gold/provider/context/budget failures produce complete fixed-category records
instead of dropping cases or exposing exception text. Timings preserve measured
precision; over-budget measurements are not clipped to pass the comparison.
Console summaries omit questions, SQL and model responses. Per-case JSONL still
contains the private evaluation inputs/results and remains gitignored.

Dataset bytes and selection are bounded and checked before database work.
`--hybrid off|on` requires `--retrieval`; the default explicitly disables hybrid
even if inherited configuration enables it. Model/provider settings still use
the existing operator-configured evaluator. **This CLI is not an offline DNS
diagnostic:** it introspects the selected database, executes gold SQL and may
call configured providers. Never run it with production settings for a fixture.

Each run creates hash-only experiment/summary receipts and a result binding.
They record source, runtime lock, dataset/selection, schema/allowlist,
model/endpoint/configuration and declared index/data-snapshot identity. Index/model aliases
are declarations, not independent artifact attestation.

`python -m eval.compare_experiments DATASET BASELINE CANDIDATE BASELINE_RECEIPT
CANDIDATE_RECEIPT` checks these bindings before applying the existing complete
paired holdout gate. It requires a semantic/hybrid off/on pair with identical
other declared identities, a declared index revision and a declared data snapshot
revision (`--data-revision SHA256`). It checks measured elapsed time and provider
counts for every case, including outages. Hashes do not prove
the inputs are authentic; no comparison authorizes production activation.

## Closed synthetic replay

The committed fixture contains 38 independently authored synthetic cases:
34 test cases (28 answers and six authorization/SQL denials), plus four excluded
training entries across the existing Bank and Pagila fixtures.

`eval/replay.py` uses production retrieval/hybrid assembly, AST validation and
read-only SQL execution. Embeddings, semantic candidates and proposed SQL are
frozen replay inputs. Every hybrid answer case must match independently stated
fixture results; losing identifier recovery cannot pass as an abstention.
Denied cases must execute no SQL. The harness checks one embedding replay,
two retrieval lookup replays and bounded frozen calls; it calls no real model.

Build the pinned runtime/check image and PostgreSQL fixture image as described
in `tools/checks/README.md`, then run from a trusted checkout:

```sh
python tools/checks/test_compare_experiments.py
python tools/checks/test_ai_replay_runner.py
python tools/checks/run_ai_replay.py \
  --image "$(docker image inspect aqua-runtime:check --format '{{.Id}}')" \
  --output /NEW/PRIVATE/PATH/ai-replay.json
```

The runner requires an exact local image ID and a create-only report outside the
source tree. It packages only the existing closed source archive plus the one
named synthetic fixture. It creates bounded disposable PostgreSQL/test
containers without host ports, host mounts, inherited DSNs, environment files or
external networking. Exact owned IDs are removed and absence verified, including
partial provisioning failures. Existing fixture budgets remain unchanged.

Passing replay proves specified synthetic retrieval/SQL behavior and harness
boundaries. It does not establish real embedding recall, model accuracy, a
production SLO or a measured financial-quality gain. Real held-out evaluation,
mixed workload capacity and the P11/P13 release gates remain required.
