"""Opt-in, unauthenticated GET-only delivery observations for Aqua's public site.

Default mode prints the fixed plan without networking. Live mode uses an
isolated, credential-free child with a hard deadline, including DNS stalls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import time
from urllib.parse import urljoin

# -I removes the script directory; restore only this fixed source directory,
# never a caller-controlled PYTHONPATH, for the reviewed local helper modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from public_delivery_receipt import classify, header_values, receipt  # noqa: E402
from public_delivery_transport import (  # noqa: E402
    BODY_BYTES,
    CONNECT_SECONDS,
    MAX_REDIRECTS,
    MAX_REQUESTS,
    ORIGINS,
    PATHS,
    READ_SECONDS,
    RECEIPT_BYTES,
    REDIRECT_STATUSES,
    REQUEST_HEADERS,
    TOTAL_SECONDS,
    InspectionStopped,
    PublicHTTPS,
    fixed_url,
    remaining,
    run_live,
)


def inspect(origin, transport, *, clock=time.monotonic):
    if origin not in ORIGINS:
        raise ValueError("origin_denied")
    result = receipt(origin, "executed")
    deadline = clock() + TOTAL_SECONDS
    for path in PATHS:
        entry = {"path": path, "complete": False, "redirects_followed": 0}
        result["checks"].append(entry)
        url = origin + path
        visited = {url}
        while True:
            response = None
            try:
                timeout = remaining(deadline, clock, CONNECT_SECONDS)
                if result["network_requests"] >= MAX_REQUESTS:
                    raise InspectionStopped("request_budget")
                if not fixed_url(url, origin):
                    raise InspectionStopped("request_denied")
                result["network_requests"] += 1
                started = clock()
                response = transport.open(
                    url,
                    origin=origin,
                    method="GET",
                    headers=dict(REQUEST_HEADERS),
                    timeout=timeout,
                )
                remaining(deadline, clock, CONNECT_SECONDS)
                if clock() - started > timeout:
                    raise InspectionStopped("connect_header_deadline")
                status = response.status
                if type(status) is not int or not 100 <= status <= 599:
                    raise InspectionStopped("response_invalid")
                entry.setdefault("initial_status", status)
                entry["status"] = status
                if status in REDIRECT_STATUSES:
                    locations = header_values(response.headers, "location")
                    if len(locations) != 1 or len(locations[0]) > 2048:
                        raise InspectionStopped("redirect_invalid")
                    target = urljoin(url, locations[0])
                    if not fixed_url(target, origin):
                        raise InspectionStopped("redirect_destination_denied")
                    if target in visited:
                        raise InspectionStopped("redirect_loop")
                    if entry["redirects_followed"] >= MAX_REDIRECTS:
                        raise InspectionStopped("redirect_limit")
                    visited.add(target)
                    entry["redirects_followed"] += 1
                    url = target
                    continue
                encoding = header_values(response.headers, "content-encoding")
                if any(
                    value.strip().lower() not in {"", "identity"} for value in encoding
                ):
                    raise InspectionStopped("content_encoding_denied")
                lengths = header_values(response.headers, "content-length")
                if lengths and (
                    len(lengths) != 1
                    or not lengths[0].isdigit()
                    or len(lengths[0]) > 12
                ):
                    raise InspectionStopped("content_length_invalid")
                if lengths and int(lengths[0]) > BODY_BYTES:
                    raise InspectionStopped("body_budget")
                body = bytearray()
                while True:
                    timeout = remaining(deadline, clock, READ_SECONDS)
                    started = clock()
                    chunk = response.read(
                        min(8192, BODY_BYTES + 1 - len(body)), timeout
                    )
                    remaining(deadline, clock, READ_SECONDS)
                    if clock() - started > timeout:
                        raise InspectionStopped("read_deadline")
                    if not isinstance(chunk, bytes):
                        raise InspectionStopped("response_invalid")
                    body.extend(chunk)
                    if len(body) > BODY_BYTES:
                        raise InspectionStopped("body_budget")
                    if not chunk:
                        break
                if lengths and len(body) != int(lengths[0]):
                    raise InspectionStopped("body_length_mismatch")
                entry.update(classify(response.headers, bytes(body)))
                entry["complete"] = True
                break
            except InspectionStopped as exc:
                entry["error"] = str(exc)
                break
            except (TimeoutError, socket.timeout):
                entry["error"] = "transport_timeout"
                break
            except Exception:
                entry["error"] = "transport_failure"
                break
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        entry["complete"] = False
                        entry["error"] = "response_close_failure"
        if entry.get("error") in {"total_deadline", "request_budget"}:
            break
    by_path = {entry["path"]: entry for entry in result["checks"]}

    def observed(path, predicate):
        entry = by_path.get(path, {})
        return predicate(entry) if entry.get("complete") else None

    result["observations"] = {
        "private_readiness_returns_404": observed(
            "/api/ready", lambda value: value["initial_status"] == 404
        ),
        "unauthenticated_profile_denied": observed(
            "/api/v1/me", lambda value: value["initial_status"] in {401, 403}
        ),
        "unknown_route_returns_404": observed(
            PATHS[4], lambda value: value["initial_status"] == 404
        ),
        "robots_serves_html": observed(
            "/robots.txt",
            lambda value: value["html_document_detected"]
            or value["content_kind"] == "html",
        ),
        "sitemap_serves_html": observed(
            "/sitemap.xml",
            lambda value: value["html_document_detected"]
            or value["content_kind"] == "html",
        ),
    }
    result["inspection_complete"] = len(result["checks"]) == len(PATHS) and all(
        item["complete"] for item in result["checks"]
    )
    return result


def live_inspection(origin):
    return run_live(origin, Path(__file__).resolve(), receipt)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="Opt in to bounded public GET requests."
    )
    parser.add_argument("--origin", choices=ORIGINS, default=ORIGINS[0])
    parser.add_argument(
        "--output",
        type=Path,
        help="Explicit create-only sanitized JSON receipt; parent must exist.",
    )
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._worker and (not args.execute or args.output is not None):
        parser.error("worker_requires_execute_without_output")
    if args.output is not None and (args.output.exists() or args.output.is_symlink()):
        parser.error("output_already_exists")
    if args.output is not None and not args.output.parent.is_dir():
        parser.error("output_parent_missing")
    if not args.execute:
        result = receipt(args.origin, "plan_only_no_network")
    elif args._worker:
        result = inspect(args.origin, PublicHTTPS())
    else:
        result = live_inspection(args.origin)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if len(encoded.encode("utf-8")) > RECEIPT_BYTES:
        raise SystemExit("receipt_budget")
    if args.output is not None:
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(encoded)
    else:
        print(encoded, end="")
    return 0 if not args.execute or result["inspection_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
