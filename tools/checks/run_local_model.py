"""Plan by default; explicit bounded local-model inference on synthetic fixtures only."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

from local_model_broker import Broker, BrokerStopped
from run_ai_replay import replay_archive
from run_backend import ROOT, docker
from local_model_resources import provision_model

sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
from eval.replay_data import load  # noqa: E402

PLAN = {
    "kind": "synthetic_local_model_plan",
    "execute": False,
    "model": "qwen3:4b",
    "think": False,
    "ssh_alias": "aqua-codex",
    "provider": "server_loopback_11434",
    "pilot_train_cases": 4,
    "heldout_test_cases": 24,
    "max_calls": 32,
    "transport_seconds": 45,
    "case_seconds": 120,
    "inference_window_seconds": 900,
    "provisioning": "existing_fixture_per_command_and_startup_bounds",
    "cleanup_seconds_per_command": 15,
    "max_prompt_bytes": 65536,
    "max_response_bytes": 1048576,
    "max_sql_bytes": 32768,
    "concurrency": 1,
    "fallback": False,
    "retrieval": False,
    "downloads": False,
    "remote_physical_exit_on_timeout": "unknown_stop_all_calls",
}


def selected_cases(raw):
    cases, digest = load(raw)
    result = []
    for dataset in ("bank", "pagila"):
        own = [c for c in cases if c["dataset"] == dataset and c["kind"] == "answer"]
        result.extend([c for c in own if c["split"] == "train"])
        result.extend([c for c in own if c["split"] == "test"][:12])
    pilot = [c for c in result if c["split"] == "train"]
    holdout = [c for c in result if c["split"] == "test"]
    if len(pilot) != 4 or len(holdout) != 24:
        raise ValueError("fixed_case_selection_invalid")
    return pilot, holdout, digest


def fixture(runner, case, action, deadline, response=None, request_sha256=None):
    value = {"id": case["id"]}
    if response is not None:
        value.update(response=response.decode(), request_sha256=request_sha256)
    raw = docker(
        "exec",
        "-i",
        "--workdir=/checks",
        runner,
        "python",
        "-B",
        "/checks/eval/local_model_fixture.py",
        case["dataset"],
        action,
        data=json.dumps(value, ensure_ascii=False).encode(),
        timeout=max(0.01, min(120, deadline - time.monotonic())),
    )
    if len(raw) > 131072:
        raise ValueError("fixture_output_budget")
    result = json.loads(raw)
    if action == "prepare" and set(result) != {"body", "request_sha256"}:
        raise ValueError("fixture_prepare_invalid")
    if action == "score" and (
        set(result) != {"status"}
        or result["status"]
        not in {
            "correct",
            "incorrect",
            "sql_denied",
            "query_failed",
            "provider_reply_invalid",
        }
    ):
        raise ValueError("fixture_score_invalid")
    return result


def evaluate(runner, case, broker, run_deadline):
    started = time.monotonic()
    deadline = min(run_deadline, started + 120)
    prepared = fixture(runner, case, "prepare", deadline)
    response = broker.send(prepared["body"], deadline)
    result = fixture(
        runner, case, "score", deadline, response, prepared["request_sha256"]
    )
    if time.monotonic() > deadline:
        raise BrokerStopped("case_deadline")
    return {
        "id": case["id"],
        "status": result["status"],
        "seconds": time.monotonic() - started,
        "provider_calls": 1,
    }


def run(image, expected_digest, output):
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image) or not re.fullmatch(
        r"[a-f0-9]{64}", expected_digest
    ):
        raise ValueError("exact_image_and_model_digest_required")
    output = output.resolve()
    if output.is_relative_to(ROOT.resolve()):
        raise ValueError("output_must_be_outside_source")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as destination:
        owned, records = [], []
        deadline = time.monotonic() + 900
        broker = Broker(expected_digest, deadline)
        report = {
            "status": "incomplete",
            "kind": "synthetic_local_model_first_attempt_qualification",
            "model_digest_declared": expected_digest,
            "model_digest_attested": False,
            "production_activation_authorized": False,
            "real_inference_requested": True,
            "remote_physical_exit_on_failure": "unknown",
            "limits": PLAN,
        }
        try:
            pilot, holdout, dataset_digest = selected_cases(
                (ROOT / "tools/checks/fixtures/ai_replay_dataset.jsonl").read_bytes()
            )
            report.update(
                dataset_sha256=dataset_digest,
                selected_case_ids=[c["id"] for c in pilot + holdout],
                image=image,
            )
            archive, _ = replay_archive()
            report["source_archive_sha256"] = hashlib.sha256(archive).hexdigest()
            runner = provision_model(
                image=image,
                run_name="aqua-local-model-" + secrets.token_hex(12),
                containers=owned,
                archive=archive,
            )
            deadline = time.monotonic() + 900
            broker.deadline = deadline
            for phase, cases in (("pilot_train", pilot), ("holdout_test", holdout)):
                for case in cases:
                    if time.monotonic() >= deadline:
                        raise BrokerStopped("run_deadline")
                    started, previous_calls = time.monotonic(), broker.calls
                    try:
                        record = evaluate(runner, case, broker, deadline)
                    except Exception:
                        records.append(
                            {
                                "id": case["id"],
                                "status": "case_failed",
                                "seconds": time.monotonic() - started,
                                "provider_calls": broker.calls - previous_calls,
                                "phase": phase,
                            }
                        )
                        raise
                    records.append(record | {"phase": phase})
                if phase == "pilot_train" and not all(
                    r["status"] == "correct" for r in records
                ):
                    raise BrokerStopped("pilot_gate_failed")
            report["status"] = "completed"
        except Exception:
            broker.stopped = True
            report["failure_category"] = "experiment_stopped"
        finally:
            remaining = []
            for container in reversed(owned):
                try:
                    docker("rm", "--force", container, timeout=15)
                    absence = subprocess.run(
                        ["docker", "container", "inspect", container],
                        capture_output=True,
                        timeout=15,
                    )
                    if absence.returncode != 1 or b"No such" not in absence.stderr:
                        remaining.append(container)
                except Exception:
                    remaining.append(container)
            attempted = {r["id"] for r in records}
            for identifier in report.get("selected_case_ids", []):
                if identifier not in attempted:
                    records.append({"id": identifier, "status": "not_completed"})
            report["holdout"] = {
                "cases": 24,
                "correct": sum(
                    r.get("phase") == "holdout_test" and r["status"] == "correct"
                    for r in records
                ),
                "completed": sum(
                    r.get("phase") == "holdout_test"
                    and r["status"] not in {"case_failed", "not_completed"}
                    for r in records
                ),
            }
            report.update(
                records=records,
                provider_calls=broker.calls,
                remote_source_sha256=broker.remote_sha256,
                remote_physical_exit=(
                    "unknown"
                    if broker.remote_exit_unknown
                    else "not_independently_proven"
                ),
                response_sha256=broker.responses,
                cleanup="failed" if remaining else "removed_and_absence_confirmed",
                remaining_ids=remaining,
            )
            if remaining:
                report["status"] = "incomplete"
            destination.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in report.items()
                        if k not in {"records", "selected_case_ids", "response_sha256"}
                    },
                    sort_keys=True,
                )
            )
    return int(report["status"] != "completed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--image")
    parser.add_argument("--expected-model-digest")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps(PLAN, sort_keys=True))
        return 0
    if not all((args.image, args.expected_model_digest, args.output)):
        parser.error("--execute requires --image, --expected-model-digest and --output")
    return run(args.image, args.expected_model_digest, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
