"""Explicit disposable P12 mixed HTTP measurement; no production configuration."""

import json
import platform
import resource
import signal
import time

from mixed_capacity_app import Runtime
from mixed_capacity_contract import LIMITS, Meter
from mixed_capacity_http import exercise


def expired(signum, frame):
    raise TimeoutError("mixed_work_deadline")


def main():
    runtime, meter = Runtime(), Meter()
    report = {
        "status": "failed",
        "python": platform.python_version(),
        "limits": LIMITS,
        "scope": "real_loopback_http_disposable_private_storage_closed_fake_analysis",
        "network": "none",
        "published_ports": False,
        "production_slo": False,
        "provider_quality_tested": False,
    }
    started = time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_SELF)
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(LIMITS["work_seconds"])
    try:
        runtime.start()
        report["measurements"] = exercise(runtime, meter)
        report["status"] = "passed"
    except BaseException as error:
        report["error_category"] = type(error).__name__
        report["failure_stage"] = runtime.phase
    finally:
        signal.alarm(0)
        report["app_cleanup"] = runtime.close()
        if not all(report["app_cleanup"].values()) or runtime.failure is not None:
            report["status"] = "failed"
        report["elapsed_seconds"] = round(time.perf_counter() - started, 4)
        report["actual_provider_calls"] = runtime.provider_attempts
        if runtime.provider_attempts:
            report["status"] = "failed"
        if "measurements" not in report:
            try:
                report["partial_http"] = meter.report()
            except ValueError:
                report["http_completion_unconfirmed"] = True
        usage = resource.getrusage(resource.RUSAGE_SELF)
        report["process_resources"] = {
            "peak_rss_bytes": usage.ru_maxrss * 1024,
            "user_cpu_seconds": round(usage.ru_utime - before.ru_utime, 4),
            "system_cpu_seconds": round(usage.ru_stime - before.ru_stime, 4),
            "machine": platform.machine(),
            "postgres_and_daemon_included": False,
        }
        report["limitations"] = [
            "Loopback HTTP with seeded synthetic sessions; no TLS, browser cookie jar, Google or password/mail acceptance.",
            "Six closed fake engines exercise real job admission and settlement, not external provider fallback or OS/GPU child exit.",
            "Slow bounded reads and actual disconnects do not saturate kernel send buffers or prove public-network backpressure capacity.",
            "One small synthetic workload and32 samples per mixed-read route; no production concurrency/SLO or p99 claim.",
        ]
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
