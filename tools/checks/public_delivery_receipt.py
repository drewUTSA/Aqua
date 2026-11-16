"""Sanitized public-delivery classifications; raw response values never escape."""

from datetime import datetime, timezone
import re

from public_delivery_transport import (
    BODY_BYTES,
    CONNECT_SECONDS,
    MAX_REDIRECTS,
    MAX_REQUESTS,
    PATHS,
    READ_SECONDS,
    TOTAL_SECONDS,
)


def header_values(headers, name):
    return [value for key, value in headers if key.lower() == name]


def media_kind(headers):
    values = header_values(headers, "content-type")
    if len(values) != 1:
        return "missing" if not values else "ambiguous"
    value = values[0].split(";", 1)[0].strip().lower()
    if value in {"text/html", "application/xhtml+xml"}:
        return "html"
    if value == "text/plain":
        return "plain"
    if value in {"application/xml", "text/xml"}:
        return "xml"
    if value == "application/json":
        return "json"
    return "other"


def classify(headers, body):
    """Do not emit even allowlisted header values: they can reflect secrets."""
    prefix = body[:8192].decode("utf-8", errors="replace").lstrip("\ufeff \t\r\n")
    frame = header_values(headers, "x-frame-options")
    frame_value = frame[0].strip().lower() if len(frame) == 1 else ""
    hsts = header_values(headers, "strict-transport-security")
    match = (
        re.search(r"(?:^|;)\s*max-age\s*=\s*(\d{1,12})\s*(?:;|$)", hsts[0], re.I)
        if len(hsts) == 1
        else None
    )
    return {
        "content_kind": media_kind(headers),
        "body_bytes": len(body),
        "html_document_detected": bool(
            re.match(r"<(?:!doctype\s+html|html\b)", prefix, re.I)
        ),
        "robots_directives_detected": bool(
            re.search(r"(?mi)^\s*(?:user-agent|disallow|allow|sitemap)\s*:", prefix)
        ),
        "sitemap_root_detected": bool(
            re.search(r"<(?:[\w-]+:)?(?:urlset|sitemapindex)(?:\s|>)", prefix, re.I)
        ),
        "csp_present": bool(header_values(headers, "content-security-policy")),
        "csp_report_only_present": bool(
            header_values(headers, "content-security-policy-report-only")
        ),
        "hsts_present": bool(hsts),
        "hsts_max_age_positive": bool(match and int(match.group(1)) > 0),
        "frame_policy": (
            frame_value
            if frame_value in {"deny", "sameorigin"}
            else ("other" if frame else "missing")
        ),
        "nosniff": any(
            value.strip().lower() == "nosniff"
            for value in header_values(headers, "x-content-type-options")
        ),
        "referrer_policy_present": bool(header_values(headers, "referrer-policy")),
    }


def receipt(origin, mode):
    return {
        "schemaVersion": 1,
        "mode": mode,
        "origin": origin,
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "unauthenticated_get_delivery_only",
        "budgets": {
            "max_requests": MAX_REQUESTS,
            "body_bytes_per_response": BODY_BYTES,
            "connect_header_seconds": CONNECT_SECONDS,
            "read_seconds": READ_SECONDS,
            "total_seconds": TOTAL_SECONDS,
            "max_redirects_per_probe": MAX_REDIRECTS,
        },
        "planned_paths": list(PATHS),
        "network_requests": 0,
        "checks": [],
        "inspection_complete": False,
        "p13_launch_complete": False,
    }
