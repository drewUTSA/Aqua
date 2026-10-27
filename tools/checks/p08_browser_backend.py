"""Fixed P08 worker entrypoint; the host owns all disposable resources."""

import argparse
import re

import p05_browser_worker
from p05_browser_protocol import emit, origin_value
from p08_browser_fixture import VisualFixture
from p08_browser_host import host

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--origin", required=True, type=origin_value)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", args.image):
            raise ValueError("fixture_image_must_be_immutable")
        raise SystemExit(
            p05_browser_worker.worker(args.origin, True, analysis_factory=VisualFixture)
            if args.worker
            else host(args.origin, args.image)
        )
    except Exception as error:
        emit(
            {
                "kind": "error",
                "category": type(error).__name__,
                "stage": p05_browser_worker.WORKER_STAGE,
            }
        )
        raise SystemExit(1) from None
