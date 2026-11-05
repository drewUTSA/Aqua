"""Explicit schema8 personal-export seam; reserved origin, immutable image only."""

import argparse

import p05_browser_worker
from p05_browser_docker import ROOT
from p05_browser_host import host
from p05_browser_protocol import emit, fixture_schema
from p08_browser_fixture import VisualFixture
from p10b_browser_fixture import secure_origin
from p10c_browser_backend import immutable_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--origin", required=True, type=secure_origin)
    parser.add_argument("--image", required=True, type=immutable_image)
    args = parser.parse_args()
    if fixture_schema(ROOT) != 8:
        raise ValueError("fixture_export_schema_required")
    flags = {
        "account_security_fixture": True,
        "account_identity_fixture": True,
        "personal_export_fixture": True,
    }
    return (
        p05_browser_worker.worker(
            args.origin, True, analysis_factory=VisualFixture, **flags
        )
        if args.worker
        else host(args.origin, args.image, True, **flags)
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
