"""Exercise the real proxy and ASGI peer contract in the network-none fixture."""

from http.client import HTTPConnection
import json
from threading import Thread
import time

from starlette.requests import Request
import uvicorn


async def echo(scope, receive, send):
    request = Request(scope)
    values = {
        "peer": request.client.host,
        "forwarded_for": request.headers.get("X-Forwarded-For"),
        "cloudflare": request.headers.get("CF-Connecting-IP"),
        "forwarded": request.headers.get("Forwarded"),
    }
    body = json.dumps(values).encode()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": body})


def observe(socket_peer, hostname, visitor, port=5173):
    # The source address belongs only to this disconnected namespace.
    conn = HTTPConnection(
        "127.0.0.1", port, timeout=2, source_address=(socket_peer, 0)
    )
    try:
        conn.request(
            "POST",
            "/api/v1/auth/password-login",
            headers={
                "Host": hostname,
                "CF-Connecting-IP": visitor,
                "X-Forwarded-For": "198.51.100.246",
                "Forwarded": "for=198.51.100.247",
            },
        )
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


def probe():
    api = uvicorn.Server(
        uvicorn.Config(
            echo,
            host="127.0.0.1",
            port=8000,
            forwarded_allow_ips="127.0.0.1",
            lifespan="off",
            log_config=None,
            access_log=False,
        )
    )
    thread = Thread(target=api.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 4
        while not api.started:
            assert time.monotonic() < deadline
            time.sleep(0.025)
        apex, alternate = "aqua-ai.us", "api.aqua-ai.us"
        visitor = "192.0.2.17"
        for _ in range(4):
            status, data = observe("127.0.0.1", apex, visitor)
            assert status == 200 and data == {
                "peer": visitor,
                "forwarded_for": visitor,
                "cloudflare": None,
                "forwarded": None,
            }
        assert observe("127.0.0.1", alternate, visitor)[0] == 429
        other = "2001:db8::21"
        status, data = observe("127.0.0.1", alternate, other)
        assert status == 200 and data["peer"] == data["forwarded_for"] == other
        for hostname in (apex, alternate):
            status, data = observe("127.0.0.2", hostname, visitor)
            assert status == 200 and data["peer"] == data["forwarded_for"] == "127.0.0.2"
            assert data["cloudflare"] is None and data["forwarded"] is None
        direct, data = observe("127.0.0.2", apex, visitor, port=8000)
        assert direct == 200 and data["peer"] == "127.0.0.2"
        return {"separate_visitors": 2, "hostnames": 2, "untrusted_peer_preserved": True}
    finally:
        api.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()


if __name__ == "__main__":
    print(json.dumps(probe()))
