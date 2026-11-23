"""Open only the selected Qwen manifest and its content-addressed model files."""

import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys
from urllib.request import ProxyHandler, Request, build_opener

IMAGE = "ollama/ollama@sha256:9c1dc45ea758396139ec0adfa52947714c61f8d1e4537a6e2daef8138e7a64a9"
MODEL = "qwen3:8b"
DIGEST = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"
MANIFEST = Path("manifests/registry.ollama.ai/library/qwen3/8b")


def verified_mounts(folder):
    root = folder.resolve(strict=True)
    if not root.is_dir() or root.anchor.startswith("\\\\"):
        raise ValueError("Choose a local Ollama models folder on this PC")

    def verified(relative, digest, size, manifest=False):
        path = root / relative
        if (
            path.resolve(strict=True) != path
            or not path.is_file()
            or path.stat().st_size != size
        ):
            raise ValueError(
                "The selected Ollama model has missing or unexpected files"
            )
        raw = None
        with path.open("rb") as stream:
            if manifest:
                raw = stream.read(65537)
                actual = hashlib.sha256(raw).hexdigest()
            else:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != digest:
                raise ValueError("The selected Ollama model failed its SHA-256 check")
        line = io.StringIO(newline="")
        csv.writer(line, lineterminator="\n").writerow(
            [
                "type=bind",
                f"source={path}",
                "target=/models/" + relative.as_posix(),
                "readonly",
            ]
        )
        return ["--mount", line.getvalue().rstrip("\n")], raw

    # The manifest is pinned before its sizes and blob names are trusted.
    if (root / MANIFEST).stat().st_size > 65536:
        raise ValueError("Unexpected Ollama model manifest")
    args, raw = verified(
        MANIFEST, DIGEST, (root / MANIFEST).stat().st_size, manifest=True
    )
    config = json.loads(raw)
    for entry in (config["config"], *config["layers"]):
        algorithm, digest = entry["digest"].split(":")
        if algorithm != "sha256" or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("Invalid model file identifier")
        mount, _ = verified(Path("blobs") / ("sha256-" + digest), digest, entry["size"])
        args.extend(mount)
    return args


def local_api(route, payload=None):
    request = Request(
        "http://127.0.0.1:11434/api/" + route,
        data=json.dumps(payload).encode() if payload else None,
        headers={"Content-Type": "application/json"},
    )
    with build_opener(ProxyHandler({})).open(
        request, timeout=165 if payload else 4
    ) as response:
        return json.loads(response.read(65537))


def check_selected(route):
    models = local_api(route)["models"]
    if [(m["name"], m["digest"]) for m in models] != [(MODEL, DIGEST)]:
        raise ValueError("Local Ollama does not have the selected model")


def preload(context_length):
    # An empty request makes Ollama load the model without generating any text.
    response = local_api(
        "generate",
        {
            "model": MODEL,
            "stream": False,
            "keep_alive": "10m",
            "options": {"num_ctx": context_length},
        },
    )
    if (
        response.get("model") != MODEL
        or response.get("done") is not True
        or response.get("response") != ""
    ):
        raise ValueError("Ollama did not complete the local preload")
    check_selected("ps")


if __name__ == "__main__":
    if sys.argv[1] == "probe":
        check_selected("tags")
    elif sys.argv[1] == "preload":
        sys.path.insert(0, "/app")
        from nl2sql.llm import NUM_CTX

        preload(NUM_CTX)
