"""Explicit real notes API fixture; fixed private data and no analytical work."""

import argparse
import re

import p05_browser_worker
from p05_browser_host import host
from p05_browser_protocol import emit, origin_value


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--origin", required=True, type=origin_value)
    parser.add_argument("--image", required=True)
    return parser.parse_args(argv)


def run(args):
    if type(args.image) is not str or not re.fullmatch(
        r"sha256:[a-f0-9]{64}", args.image
    ):
        raise ValueError("fixture_notes_image_invalid")
    return (
        p05_browser_worker.worker(args.origin, notes_fixture=True)
        if args.worker
        else host(args.origin, args.image, notes_fixture=True)
    )


if __name__ == "__main__":
    try:
        raise SystemExit(run(arguments()))
    except Exception as error:  # noqa: BLE001 - no credential/input diagnostics
        emit(
            {
                "kind": "error",
                "category": type(error).__name__,
                "stage": p05_browser_worker.WORKER_STAGE,
            }
        )
        raise SystemExit(1) from None
