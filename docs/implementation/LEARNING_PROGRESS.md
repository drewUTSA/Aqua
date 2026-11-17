# Aqua learning and companion foundations — November 16, 2026

> **Latest session: stopped November 17 UTC.** Read the [complete next-chat handoff](PERSONAL_COMPUTER_RESUME_20261117.md).
> Production remains on schema 8; the current operator is unfinished. Earlier sections retain their historical scope.

## Subsequent measured experiments

The approved20train/5validation public packet was actually trained with a
pinned Qwen3-4B NF4 QLoRA recipe on the local RTX5070. Five optimizer updates
changed the adapter and lowered train/validation loss. The complete paired
protected test regressed from33/67 to30/67 exact matches (43→39 lenient) and was
slower. **This adapter is rejected: do not convert, import or activate it, and
do not train against the67 protected failures.** Lower loss is not SQL accuracy.
No production model tags or weights changed. The original source-preparation
description below is historical; its future-training language is superseded.

A separate new synthetic tool-selection packet completed32 real calls with
fresh installed-digest checks: qwen3:4b5/16 correct,10 incorrect and1 denied;
qwen3:8b10/16 correct and6 incorrect. Both retain the full16-case denominator.
No proposed tool executed. Neither model passes this packet or qualifies an
automatic planner. Preserve the packet as evaluation evidence and develop
against separately reviewed examples before a new independent evaluation.

[Reviewed help tools](COMPANION_HELP_TOOLS.md) are a separate default-off source
addition: source-cited deterministic help and explicit draft preparation.
They do not claim model learning, persistent memory or autonomous execution.
Actual image/backend/browser and current PR/main CI gates remain mandatory.

## Original source-preparation checkpoint

Ben requested broad Aqua context, useful trends and a companion that improves
through measured learning. This source slice prepares four related components;
it does not enable a conversational agent or update production model weights.
No GH company corpus, account history, credentials or private configuration was
imported. The source-only qualification and release boundaries remain distinct.

## Measured local-model baseline

The existing server-local `qwen3:4b`, installed digest
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`,
completed four training pilots and 24 held-out synthetic SQL cases. It answered
22/24 test cases correctly using 28 serial first-attempt calls overall, with
thinking, fallback and retrieval disabled. All cases, including two incorrect
answers, remain recorded. The test set is not training material.

The measured held-out case p95 was 2.531 seconds including SSH and disposable
fixture overhead, over 50.641 seconds of held-out case work. These small synthetic
measurements are not production latency, financial-quality or hybrid-retrieval
qualification. Installed-model identity checks are not independent training
provenance. No provider, feature-default or production routing changed.

The source-bound component receipt and six unchanged harness-file hashes are
in `evidence/learning/`. That precommit component snapshot differs from the final
combined source archive; exact-head CI must qualify the final candidate. The
runtime/SQL pipeline and frozen dataset were unchanged across the experiment.

Before inference, all 28 prepare/score cases, two production capture tests and
six SQL/request-binding denials passed in network-none PostgreSQL fixtures.
The broker has fixed destination/model/options, verified installed digest,
strict byte/call/deadline bounds and terminal failure behavior. It never sends
gold SQL/rows to the model. Every owned container was removed and absence verified.
See [local-model qualification](LOCAL_MODEL_QUALIFICATION.md).

## Context and capabilities

[The companion context contract](COMPANION_OFFLINE_CONTRACT.md) assembles bounded,
fresh, explicitly approved Aqua help, dataset metadata, owned question text and
supported display preferences. Owner/scope/schema bindings are mandatory;
authentication/session/grant fields are excluded from generated context. Text
remains untrusted data. The closed capability/artifact vocabulary defaults to
empty and never executes a tool. This is qualification code, not stored memory
or a live assistant endpoint.

## Numerical learning

[The monthly trend tool](MONTHLY_TREND_LEARNING.md) fits bounded Decimal OLS
coefficients from explicitly complete consecutive monthly aggregates. It reports
separate approximate historical insights and chronological evaluation against a
last-observation baseline, including insufficient history and underperformance.
Existing exact financial rows and charts are untouched. It makes no database
call, future-performance or causation claim and does not train Ollama weights.

## Reviewed examples toward weight training

[The supervised export foundation](SFT_EXPORT_FOUNDATION.md) reuses the existing
reviewed knowledge/SQL compiler and production prompt/response format. It binds
reviewed source/schema/test bytes, requires rights/review declarations, rejects
ID/question/canonical-SQL duplicates across all partitions, clears ambient
conversation history and defaults to a count/hash dry-run. Explicit exports are
create-only outside the app. Declarations are not independently attested; semantic
leakage and execution correctness still need review. No corpus was manufactured
or promoted from the test set, and no actual training was performed.

The intended first weight-training candidate is original Qwen3-4B with a pinned
tokenizer/base and a supervised QLoRA adapter. The existing Ollama GGUF is an
inference artifact. The PC's Docker GPU probe successfully initialized CUDA and
found one device, with no weights/packages downloaded and no training step. This
does not prove that the future trainer fits or performs correctly. The host has
about 31.6 GiB RAM; its Docker VM reports about 15.4 GiB. Future training needs a
locked compatible stack, reviewed varied corpus, correct loss masking/template,
bounded compute and a candidate evaluation before conversion/import under a new
tag. Existing models remain baselines. [Qwen's training guide](https://qwen.readthedocs.io/en/latest/training/unsloth.html)
and [the pinned official base](https://huggingface.co/Qwen/Qwen3-4B/tree/1cfa9a7208912126459214e8b04321603b3df60c)
describe the underlying model/training path; no training framework is an Aqua
runtime dependency.

## Verification and remaining work

The four new backend test modules pass 119 focused tests in the pinned,
network-none Linux runtime, plus 11 pure broker/runner guards. Independent
reviews covered the broker, numerical tool, context and export contracts.
Formatting/lint and source/lock checks remain mandatory with every retained
backend/security/browser check in exact-head PR and distinct main CI.

The live analytical endpoint still returns authoritative NXDOMAIN. P11 encrypted
backup/authority recovery and retention are unresolved; schema8 remains deployed.
The rejected trained adapter, production companion integration/owned memory,
live trend input qualification, mixed workload capacity, physical-device mobile
acceptance and the P13 release gates remain open. None of these offline modules
adds an analytical grant, arbitrary tool/SQL execution or a production capability.
