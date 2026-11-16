"""Run the pipeline over a question set and report execution accuracy.

From the repo root, with the backend's virtual environment active and
.env filled in (the model must be reachable):

    python eval/run_eval.py                    # test questions, no retrieval
    python eval/run_eval.py --retrieval        # same questions, with retrieval
    python eval/run_eval.py --retrieval --hybrid on  # explicitly qualify hybrid
    python eval/run_eval.py --limit 5          # quick smoke run
    python eval/run_eval.py --ids t47          # rerun one question, e.g. after an outage
    python eval/run_eval.py --model ollama     # compare against the other provider
    python eval/run_eval.py --fallback         # Gemini with the app's Ollama fallback
    python eval/run_eval.py --pause 8          # stay under a per-minute token limit
    python eval/run_eval.py --check-gold       # run only the gold SQL, no model

Each run writes eval/results/<time>-<mode>.jsonl (one line per question)
and a .summary.json next to it. eval/results/ is gitignored; copy the
summary numbers into docs/decisions.md when they settle a decision.

Gold SQL runs through the same validator and read-only connection as the
app, so the comparison is like for like.
"""

from __future__ import annotations

from dataclasses import replace
import datetime as dt
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from eval import arguments, case_runner  # noqa: E402
from eval.metrics import exact_match, lenient_match, summarize_run  # noqa: E402
from eval.compare_runs import MAX_BYTES, indexed, records as parse_records  # noqa: E402
from eval.experiment import (  # noqa: E402
    create_text,
    digest,
    experiment,
    source_identity,
    write_json,
)
from nl2sql.config import load_settings  # noqa: E402
from nl2sql.db import DatabaseError as DatabaseError  # noqa: E402
from nl2sql.execute import execute  # noqa: E402
from nl2sql.llm import LLMError as LLMError  # noqa: E402
from nl2sql.pipeline import answer_question  # noqa: E402
from nl2sql.schema import get_schema  # noqa: E402
from nl2sql.validate import validate_sql  # noqa: E402

DEFAULT_DATASET = ROOT / "eval" / "datasets" / "pagila_v1.jsonl"
RESULTS = ROOT / "eval" / "results"


def load(path: Path, split: str) -> list[dict[str, Any]]:
    return select_items(read_dataset(path), split)


def read_dataset(path: Path) -> bytes:
    with path.open("rb") as source:
        return source.read(MAX_BYTES + 1)


def select_items(raw: bytes, split: str) -> list[dict[str, Any]]:
    items = parse_records(raw)
    indexed(items)  # Duplicate IDs cannot silently alter a selected holdout.
    for item in items:
        if (
            item.get("split") not in {"train", "test"}
            or item.get("difficulty") not in {"easy", "medium", "hard"}
            or not isinstance(item.get("question"), str)
            or not 1 <= len(item["question"]) <= 12000
            or not isinstance(item.get("sql"), str)
            or not 1 <= len(item["sql"]) <= 32768
            or ("ordered" in item and type(item["ordered"]) is not bool)
        ):
            raise ValueError("dataset_case_invalid")
    return [i for i in items if split == "all" or i["split"] == split]


def run_gold(item: dict[str, Any], settings, schema) -> list[tuple]:
    query = validate_sql(item["sql"], allowed_tables=schema.allowed_tables)
    return execute(query, settings).rows


def check_gold(items: list[dict[str, Any]], settings, schema) -> int:
    return case_runner.check_gold(
        items, settings, schema, gold_runner=run_gold, clock=time
    )


def evaluate(item: dict[str, Any], settings, schema, retriever) -> dict[str, Any]:
    return case_runner.evaluate(
        item,
        settings,
        schema,
        retriever,
        gold_runner=run_gold,
        pipeline=answer_question,
        exact_scorer=exact_match,
        lenient_scorer=lenient_match,
        clock=time,
    )


def main(argv: list[str] | None = None) -> int:
    parser, args = arguments.parse(argv, DEFAULT_DATASET, __doc__.splitlines()[0])

    settings = replace(
        load_settings(),
        llm_fallback=args.fallback,
        retrieval=args.retrieval,
        retrieval_hybrid_enabled=args.hybrid == "on",
    )
    if args.model:
        settings = replace(settings, llm_provider=args.model)
    dataset_bytes = read_dataset(args.dataset)
    items = select_items(dataset_bytes, args.split)
    if args.ids:
        requested = [i.strip() for i in args.ids.split(",")]
        wanted = set(requested)
        if (
            "" in wanted
            or len(wanted) != len(requested)
            or not wanted <= {item["id"] for item in items}
        ):
            parser.error("--ids must name distinct cases in the selected split")
        items = [i for i in items if i["id"] in wanted]
    items = items[: args.limit]
    if not items:
        parser.error("selected dataset is empty")
    schema = get_schema(settings)
    if args.check_gold:
        return check_gold(items, settings, schema)

    retriever = None
    if args.retrieval:
        from nl2sql.retrieval.select import VectorRetriever

        retriever = VectorRetriever(settings)

    mode = (
        (
            "retrieval-hybrid"
            if settings.retrieval_hybrid_enabled
            else "retrieval-semantic"
        )
        if args.retrieval
        else "baseline"
    )
    receipt = experiment(
        dataset_bytes,
        items,
        settings,
        schema,
        source_sha256=source_identity(ROOT),
        retrieval=args.retrieval,
        index_revision=args.index_revision,
        data_revision=args.data_revision,
    )
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if RESULTS.is_symlink():
        raise ValueError("results_directory_invalid")
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{stamp}-{mode}-{receipt.sha256[:12]}-{secrets.token_hex(4)}.jsonl"
    write_json(out.with_suffix(".experiment.json"), receipt.metadata())
    records = []
    with create_text(out) as handle:
        for number, item in enumerate(items, start=1):
            if args.pause and number > 1:
                time.sleep(args.pause)
            record = evaluate(item, settings, schema, retriever)
            records.append(record)
            handle.write(json.dumps(record, default=str) + "\n")
            handle.flush()
            mark = "PASS" if record["lenient"] else record["status"].upper()
            print(f"[{number}/{len(items)}] {mark:12}")

    summary = summarize_run(records) | {
        "mode": mode,
        "split": args.split,
        "experiment_sha256": receipt.sha256,
    }
    write_json(out.with_suffix(".summary.json"), summary)
    write_json(
        out.with_suffix(".receipt.json"),
        {
            "experiment_sha256": receipt.sha256,
            "results_sha256": digest(out.read_bytes()),
            "cases": len(records),
            "experiment": receipt.metadata(),
        },
    )
    print(json.dumps(summary, indent=2))
    print(f"\nPer-question results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
