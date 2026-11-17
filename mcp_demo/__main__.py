"""Run only the local fictional stdio demonstration in its isolated SDK env."""

import argparse
import logging
import sys
from importlib.metadata import version

from mcp_demo.protocol import PERSONAS, DemoDenied, actor_for


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise DemoDenied("demo_launch_invalid")


def main():
    logging.disable(logging.CRITICAL)
    parser = SafeParser(description="Aqua fictional bank MCP demo over stdio only.")
    parser.add_argument(
        "--persona",
        choices=PERSONAS,
        default="none",
        help="Explicit host-selected fictional persona; omitted means no data/tool grants.",
    )
    args = parser.parse_args()
    if version("mcp") != "2.3.0":
        raise DemoDenied("demo_sdk_version_invalid")
    import anyio

    from mcp_demo.server import run_stdio

    anyio.run(run_stdio, actor_for(args.persona))
    return 0


if __name__ == "__main__":
    try:
        result = main()
    except KeyboardInterrupt:
        result = 130
    except Exception:
        sys.stderr.write(
            "Aqua fictional demo stopped: invalid configuration, request or transport.\n"
        )
        result = 1
    raise SystemExit(result)
