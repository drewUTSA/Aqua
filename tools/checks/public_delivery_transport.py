"""Fixed HTTPS transport and hard child-process deadline; no ambient credentials."""

import http.client
import json
import os
import ssl
import subprocess
import sys
from urllib.parse import urlsplit

ORIGINS = ("https://aqua-ai.us", "https://www.aqua-ai.us")
PATHS = (
    "/",
    "/signin",
    "/robots.txt",
    "/sitemap.xml",
    "/_aqua_public_delivery_missing_20261116",
    "/api/ready",
    "/api/v1/me",
)
MAX_REQUESTS = 8  # Seven probes and, at most, one extra same-origin redirect.
MAX_REDIRECTS = 1
BODY_BYTES = 65_536
CONNECT_SECONDS = 3.0
READ_SECONDS = 2.0
TOTAL_SECONDS = 20.0
RECEIPT_BYTES = 32_768
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
REQUEST_HEADERS = {
    "Accept": "text/html,text/plain,application/json,application/xml;q=0.9,*/*;q=0.1",
    "Accept-Encoding": "identity",
    "Connection": "close",
    "User-Agent": "Aqua-public-delivery-check/1",
}


class InspectionStopped(Exception):
    """Only fixed categories cross into the receipt."""


def remaining(deadline, clock, maximum):
    seconds = deadline - clock()
    if seconds <= 0:
        raise InspectionStopped("total_deadline")
    return min(maximum, seconds)


def fixed_url(url, origin):
    """Reject credentials, queries, fragments and any non-fixed destination."""
    if origin not in ORIGINS or not isinstance(url, str):
        return False
    try:
        value = urlsplit(url)
        return (
            value.scheme == "https"
            and value.netloc == urlsplit(origin).netloc
            and value.username is None
            and value.password is None
            and value.port is None
            and value.path in PATHS
            and not value.query
            and not value.fragment
        )
    except ValueError:
        return False


class HTTPResponse:
    def __init__(self, connection, response):
        self.connection = connection
        self.response = response
        self.status = response.status
        self.headers = response.getheaders()

    def read(self, size, timeout):
        if self.response.fp is None:
            return b""
        # Connection: close can detach the socket from HTTPSConnection while
        # HTTPResponse still owns its file; bound that actual reader as well.
        raw = getattr(getattr(self.response, "fp", None), "raw", None)
        connection_socket = self.connection.sock or getattr(raw, "_sock", None)
        if connection_socket is None:
            raise InspectionStopped("response_socket_unavailable")
        connection_socket.settimeout(timeout)
        return self.response.read1(size)

    def close(self):
        self.response.close()
        self.connection.close()


class PublicHTTPS:
    """Direct HTTPS only: http.client has no proxy, netrc or cookie handling."""

    def open(self, url, *, origin, method, headers, timeout):
        if method != "GET" or not fixed_url(url, origin):
            raise InspectionStopped("request_denied")
        if headers != REQUEST_HEADERS:
            raise InspectionStopped("request_headers_denied")
        target = urlsplit(url)
        connection = http.client.HTTPSConnection(
            target.hostname, timeout=timeout, context=ssl.create_default_context()
        )
        try:
            connection.request("GET", target.path, headers=dict(REQUEST_HEADERS))
            return HTTPResponse(connection, connection.getresponse())
        except Exception:
            connection.close()
            raise


def worker_environment():
    """WinSock needs SystemRoot; never inherit proxies, credentials or PATH."""
    if os.name == "nt":
        return {"SystemRoot": os.environ.get("SystemRoot", "C:/Windows")}
    return {}


def run_live(origin, script_path, receipt_factory):
    """A hard process deadline bounds otherwise uninterruptible resolver work."""
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(script_path),
                "--execute",
                "--origin",
                origin,
                "--_worker",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=TOTAL_SECONDS,
            env=worker_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if completed.returncode not in {0, 1} or len(completed.stdout) > RECEIPT_BYTES:
            raise ValueError("worker_failed")
        value = json.loads(completed.stdout)
        if value.get("origin") != origin or value.get("mode") != "executed":
            raise ValueError("worker_invalid")
        return value
    except subprocess.TimeoutExpired:
        category = "hard_total_deadline"
    except Exception:
        category = "worker_failure"
    value = receipt_factory(origin, "executed")
    value["error"] = category
    value["network_requests"] = None  # A terminated worker may have sent requests.
    return value
