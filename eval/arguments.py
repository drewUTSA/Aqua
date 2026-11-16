"""Explicit evaluator options cannot inherit an unrequested hybrid setting."""

import argparse
import math
from pathlib import Path

from eval.experiment import revision


def parse(argv, default_dataset, description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--dataset", type=Path, default=default_dataset)
    parser.add_argument("--split", choices=["test", "train", "all"], default="test")
    parser.add_argument(
        "--retrieval", action="store_true", help="use the vector retriever"
    )
    parser.add_argument(
        "--hybrid",
        choices=["off", "on"],
        help="requires --retrieval; defaults to off, ignoring inherited hybrid configuration",
    )
    parser.add_argument(
        "--index-revision",
        type=revision,
        help="declared retrieval snapshot SHA-256; not independently attested",
    )
    parser.add_argument(
        "--data-revision",
        type=revision,
        help="declared analytical data snapshot SHA-256; not independently attested",
    )
    parser.add_argument("--limit", type=int, help="only the first N questions")
    parser.add_argument(
        "--ids", help="only these question ids, comma separated, e.g. t47,t50"
    )
    parser.add_argument(
        "--check-gold", action="store_true", help="run gold SQL only; no model calls"
    )
    parser.add_argument(
        "--model",
        choices=["ollama", "gemini"],
        help="provider to evaluate; default is LLM_PROVIDER from .env",
    )
    parser.add_argument(
        "--fallback",
        action="store_true",
        help="let Gemini outages fall back to Ollama, as the app does; off by "
        "default so the scores measure the chosen model only",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.0,
        help="seconds to wait between questions, to stay under a free-tier "
        "tokens-per-minute limit (Gemma 4 26B: 16,000 input tokens a minute)",
    )
    args = parser.parse_args(argv)
    if args.hybrid is not None and not args.retrieval:
        parser.error("--hybrid requires --retrieval")
    if args.index_revision is not None and not args.retrieval:
        parser.error("--index-revision requires --retrieval")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if not math.isfinite(args.pause) or not 0 <= args.pause <= 3600:
        parser.error("--pause must be finite and between 0 and 3600")

    return parser, args
