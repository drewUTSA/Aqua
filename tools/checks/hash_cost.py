"""Synthetic parameter microbenchmark, only inside the bounded Linux candidate."""

from concurrent.futures import ThreadPoolExecutor
import json
import resource
import time

from auth.password_hash import ITERATIONS, MEMORY_KIB, PARALLELISM, PasswordHasher


def measure() -> dict:
    def sample(index: int) -> tuple[float, float]:
        hasher = PasswordHasher()
        password = f"synthetic cost fixture secret {index}!"
        start = time.monotonic()
        encoded = hasher.hash(password)
        hashed = time.monotonic()
        assert hasher.verify(password, encoded)
        return (hashed - start) * 1000, (time.monotonic() - hashed) * 1000

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as workers:
        samples = list(workers.map(sample, range(32)))
    timing = {}
    for index, name in enumerate(("hash", "verify")):
        values = sorted(item[index] for item in samples)
        timing[name] = {
            "p50_ms": round(values[15], 3),
            "p95_ms": round(values[30], 3),
            "max_ms": round(values[-1], 3),
        }
    return {
        "status": "passed",
        "samples": 32,
        "concurrency": 2,
        "parameters": {
            "memory_kib": MEMORY_KIB,
            "iterations": ITERATIONS,
            "parallelism": PARALLELISM,
        },
        "timing": timing,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "limitations": "Synthetic microbenchmark in a two-CPU container; not full login latency, production capacity or a substitute for P12 mixed load. No account, password, encoded hash or provider traffic is emitted.",
    }


if __name__ == "__main__":
    print(json.dumps(measure()))
