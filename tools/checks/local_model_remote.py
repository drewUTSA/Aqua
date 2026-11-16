"""Fixed server-local Ollama broker body; executed only by explicit operator opt-in."""

import hashlib
from http.client import HTTPConnection
import json
import signal
import sys

MODEL = "qwen3:4b"
OPTIONS = {
    "temperature": 0.7,
    "top_p": 0.8,
    "top_k": 20,
    "seed": 42,
    "num_ctx": 16384,
    "num_predict": 4096,
}
FORMAT = {
    "type": "object",
    "properties": {"sql": {"type": "string"}},
    "required": ["sql"],
}
MAX_BODY = 1048576


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_field")
        result[key] = value
    return result


def validate(request):
    if type(request) is not dict or set(request) != {"digest", "body"}:
        raise ValueError("request_invalid")
    digest = request["digest"]
    if (
        type(digest) is not str
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("digest_invalid")
    body = request["body"]
    if type(body) is not dict or set(body) != {
        "model",
        "messages",
        "stream",
        "think",
        "options",
        "format",
    }:
        raise ValueError("body_invalid")
    if (
        body["model"] != MODEL
        or body["stream"] is not False
        or body["think"] is not False
        or body["options"] != OPTIONS
        or body["format"] != FORMAT
    ):
        raise ValueError("policy_invalid")
    messages = body["messages"]
    if type(messages) is not list or len(messages) != 2:
        raise ValueError("messages_invalid")
    total = 0
    for item, role in zip(messages, ("system", "user")):
        if (
            type(item) is not dict
            or set(item) != {"role", "content"}
            or item["role"] != role
            or type(item["content"]) is not str
        ):
            raise ValueError("messages_invalid")
        total += len(item["content"].encode())
    if not 0 < total <= 65536:
        raise ValueError("prompt_budget")
    return digest, body


def request_json(method, path, body=None):
    connection = HTTPConnection("127.0.0.1", 11434, timeout=45)
    try:
        connection.request(
            method,
            path,
            body=body,
            headers={"Content-Type": "application/json", "Accept-Encoding": "identity"},
        )
        response = connection.getresponse()
        raw = response.read(MAX_BODY + 1)
        if (
            response.status != 200
            or len(raw) > MAX_BODY
            or response.getheader("Content-Encoding", "identity") != "identity"
        ):
            raise ValueError("provider_response_invalid")
        return raw
    finally:
        connection.close()


def alarm(signum, frame):
    raise TimeoutError("transport_deadline")


def main():
    # The alarm covers inventory, HTTP headers and the complete response body.
    signal.signal(signal.SIGALRM, alarm)
    signal.alarm(45)
    submitted = False
    try:
        raw = sys.stdin.buffer.read(131073)
        if len(raw) > 131072:
            raise ValueError("request_budget")
        digest, body = validate(json.loads(raw, object_pairs_hook=unique))
        tags = json.loads(request_json("GET", "/api/tags"), object_pairs_hook=unique)
        matches = [m for m in tags.get("models", []) if m.get("name") == MODEL]
        if (
            len(matches) != 1
            or matches[0].get("digest", "").removeprefix("sha256:") != digest
        ):
            raise ValueError("installed_model_identity_mismatch")
        submitted = True
        response = request_json(
            "POST", "/api/chat", json.dumps(body, separators=(",", ":")).encode()
        )
        value = json.loads(response, object_pairs_hook=unique)
        if (
            type(value) is not dict
            or value.get("model") != MODEL
            or value.get("done") is not True
        ):
            raise ValueError("provider_identity_or_completion_invalid")
        print(
            json.dumps(
                {
                    "status": "ok",
                    "body": response.decode(),
                    "response_sha256": hashlib.sha256(response).hexdigest(),
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        # Closing SSH/HTTP cannot prove that the daemon's GPU work has exited.
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "remote_physical_exit": "unknown" if submitted else "not_submitted",
                }
            )
        )
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
