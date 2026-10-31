"""Dedicated reserved-HTTPS entry; never an arbitrary origin/worker/provider."""

import argparse
import re

import p05_browser_worker
from p05_browser_host import host
from p05_browser_protocol import emit
from p08_browser_fixture import VisualFixture
from p10b_browser_fixture import secure_origin

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--origin", required=True, type=secure_origin)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", args.image):
            raise ValueError("fixture_image_must_be_immutable")
        raise SystemExit(
            p05_browser_worker.worker(
                args.origin,
                True,
                analysis_factory=VisualFixture,
                account_security_fixture=True,
            )
            if args.worker
            else host(args.origin, args.image, True, account_security_fixture=True)
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
