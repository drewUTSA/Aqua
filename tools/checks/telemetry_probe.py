"""Bounded offline exercise for CVE-2026-114603's tracestate length guard.

Run inside a disposable runtime image, never against an application endpoint.
Oversized inputs are at most 8,193 ASCII bytes. A parser-entry sentinel stops
the old version before its vulnerable split; no timing threshold is involved.
"""

import argparse
from importlib.metadata import version
import json
import logging
from unittest.mock import patch

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.trace.span import TraceState

TRACE_ID = "12345678901234567890123456789012"
SPAN_ID = "1234567890123456"
TRACEPARENT = f"00-{TRACE_ID}-{SPAN_ID}-01"
LIMIT = 8192
PROPAGATOR = TraceContextTextMapPropagator()


class ParserReached(Exception):
    """Stop before any tracestate splitting, including in the vulnerable pin."""


def extract(headers: list[str]) -> trace.SpanContext:
    """Use the real propagation entry point and verify traceparent survives."""
    assert sum(len(value.encode("ascii")) for value in headers) <= 16384
    context = PROPAGATOR.extract({"traceparent": [TRACEPARENT], "tracestate": headers})
    span_context = trace.get_current_span(context).get_span_context()
    assert span_context.is_valid, "valid synthetic traceparent was discarded"
    assert span_context.is_remote, "remote traceparent was not preserved"
    assert span_context.trace_id == int(TRACE_ID, 16), "trace ID changed"
    assert span_context.span_id == int(SPAN_ID, 16), "span ID changed"
    return span_context


def normal_recovery() -> None:
    """The actual parser must still accept normal headers after each exercise."""
    result = extract(["a=b, c=d"])
    assert dict(result.trace_state.items()) == {"a": "b", "c": "d"}


def main() -> None:
    """Prove guard placement, combined-header counting, boundary and recovery."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expect",
        choices=("guarded", "unguarded"),
        default="guarded",
        help="unguarded is only for confirming the old pin's exposed parser path",
    )
    args = parser.parse_args()
    # Reports contain fixed outcomes, never raw header values or warning bodies.
    logging.disable(logging.CRITICAL)
    normal_recovery()
    oversized = {
        "single": ["a=b" + "\t" * 8189 + "x"],
        "combined": ["a=b" + " " * 4093, "c=d" + " " * 4093],
    }
    outcomes = []
    for name, headers in oversized.items():
        combined_length = sum(map(len, headers)) + len(headers) - 1
        assert combined_length == LIMIT + 1
        reached = False
        with patch.object(
            TraceState, "from_header", side_effect=ParserReached
        ) as entry:
            try:
                result = extract(headers)
            except ParserReached:
                reached = True
            else:
                assert not result.trace_state, "oversized tracestate was retained"
            assert entry.call_count == int(reached), "unexpected parser-entry count"
        assert reached == (
            args.expect == "unguarded"
        ), f"{name}: expected {args.expect} oversized-header parser path"
        normal_recovery()
        outcomes.append(
            {
                "case": name,
                "combined_characters": combined_length,
                "parser_entered": reached,
                "normal_header_recovery": "passed",
            }
        )

    # These run uninstrumented only on the fixed pin: valid whitespace padding
    # at exactly 8,192 characters must remain accepted, including the join comma.
    boundaries = 0
    if args.expect == "guarded":
        for headers, expected in (
            (["a=b" + " " * 8189], {"a": "b"}),
            (["a=b" + " " * 4093, "c=d" + " " * 4092], {"a": "b", "c": "d"}),
        ):
            assert sum(map(len, headers)) + len(headers) - 1 == LIMIT
            assert dict(extract(headers).trace_state.items()) == expected
            boundaries += 1
        normal_recovery()

    print(
        json.dumps(
            {
                "status": (
                    "passed" if args.expect == "guarded" else "exposure_confirmed"
                ),
                "package": "opentelemetry-api",
                "version": version("opentelemetry-api"),
                "cases": outcomes,
                "exact_boundary_checks": boundaries,
                "maximum_header_bytes": LIMIT + 1,
                "limitations": "Offline propagation only; no live endpoint or CPU benchmark.",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
