"""Capture/replay the production HTTP request without opening a network socket."""

import hashlib
import httpx
import json


def body_digest(body):
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Client:
    def __init__(self, response=None, expected=None):
        self.raw = (
            response
            if response is not None
            else b'{"model":"qwen3:4b","message":{"content":"{\\"sql\\":\\"SELECT 1\\"}"}}'
        )
        self.expected, self.body, self.calls = expected, None, 0

    def stream(self, method, url, *, json):
        if self.calls or method != "POST" or url != "http://127.0.0.1:11434/api/chat":
            raise ValueError("capture_protocol_invalid")
        self.calls += 1
        self.body = json
        if self.expected is not None and body_digest(json) != self.expected:
            raise ValueError("production_request_changed")
        return self

    def __enter__(self):
        self.response = httpx.Response(
            200,
            content=self.raw,
            request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
        )
        return self.response

    def __exit__(self, *args):
        self.response.close()
        return False
