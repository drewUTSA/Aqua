"""Strict opt-in schema7 identity fixture; no real Google, mail or network."""

import argparse
import re
import p05_browser_worker
from p05_browser_docker import ROOT
from p05_browser_host import host
from p05_browser_protocol import emit, fixture_schema
from p08_browser_fixture import VisualFixture
from p10b_browser_fixture import secure_origin


def immutable_image(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise ValueError("fixture_image_must_be_immutable")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--origin", required=True, type=secure_origin)
    parser.add_argument("--image", required=True, type=immutable_image)
    args = parser.parse_args()
    if fixture_schema(ROOT) != 7:
        raise ValueError("fixture_identity_schema_required")
    return (
        p05_browser_worker.worker(
            args.origin,
            True,
            analysis_factory=VisualFixture,
            account_security_fixture=True,
            account_identity_fixture=True,
        )
        if args.worker
        else host(
            args.origin,
            args.image,
            True,
            account_security_fixture=True,
            account_identity_fixture=True,
        )
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit(
            {
                "kind": "error",
                "category": type(error).__name__,
                "stage": p05_browser_worker.WORKER_STAGE,
            }
        )
        raise SystemExit(1) from None
