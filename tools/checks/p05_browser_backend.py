"""CLI for the isolated, real-schema P05 browser backend fixture.

No production dotenv, account, provider or database is used. Only the in-memory
browser pipe carries synthetic credentials/proofs. Never record that pipe.
"""

import argparse

import p05_browser_worker
from p05_browser_host import host
from p05_browser_protocol import DEFAULT_IMAGE, emit, origin_value

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--origin", required=True, type=origin_value)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    arguments = parser.parse_args()
    try:
        raise SystemExit(
            p05_browser_worker.worker(arguments.origin)
            if arguments.worker
            else host(arguments.origin, arguments.image)
        )
    except Exception as error:  # noqa: BLE001 - outer process boundary emits type only
        emit(
            {
                "kind": "error",
                "category": type(error).__name__,
                "stage": p05_browser_worker.WORKER_STAGE,
                "module": (
                    getattr(error, "name", None)
                    if isinstance(error, ModuleNotFoundError)
                    else None
                ),
            }
        )
        raise SystemExit(1) from None
