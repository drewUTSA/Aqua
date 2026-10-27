"""Two metadata frames prove actual nginx delivery before upstream completion."""

from http.client import HTTPConnection
import json
import time

PATH = "/api/v1/analysis-requests/00000000-0000-4000-8000-000000000001/events"
FIRST = b'event: progress\ndata: {"sequence":1,"state":"running"}\n\n'
LAST = b'event: progress\ndata: {"sequence":2,"state":"complete"}\n\n'
DELAY = 1.0


def respond(handler) -> bool:
    if handler.path != PATH:
        return False
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Content-Length", str(len(FIRST) + len(LAST)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(FIRST)
    handler.wfile.flush()
    time.sleep(DELAY)
    handler.wfile.write(LAST)
    handler.wfile.flush()
    return True


def verify() -> dict:
    connection = HTTPConnection("127.0.0.1", 5173, timeout=3)
    started = time.monotonic()
    try:
        connection.request("GET", PATH, headers={"Accept": "text/event-stream"})
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type") == "text/event-stream"
        first = response.read(len(FIRST))
        first_seconds = time.monotonic() - started
        last = response.read(len(LAST))
        total_seconds = time.monotonic() - started
        assert first == FIRST and last == LAST
        assert first_seconds < DELAY * 0.7, "nginx_buffered_metadata_progress"
        assert total_seconds >= DELAY * 0.9
        assert response.getheader("Content-Encoding") is None
        return {
            "status": "passed",
            "frames": 2,
            "bytes": len(FIRST) + len(LAST),
            "first_frame_seconds": round(first_seconds, 3),
            "upstream_complete_seconds": round(total_seconds, 3),
            "payload": "fixed_synthetic_metadata_only",
        }
    finally:
        connection.close()


if __name__ == "__main__":
    print(json.dumps(verify()))
