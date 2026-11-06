"""Bounded installed publisher with an explicit reviewed image/code profile pin."""

import argparse
import json
import re

if __package__:
    from .operator_files import PRIVATE, pinned
    from .publisher_launcher import launch
else:
    from operator_files import PRIVATE, pinned
    from publisher_launcher import launch


def execute(expected: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise RuntimeError("retirement_publisher_profile_pin_required")
    value = pinned(PRIVATE / "host/publisher.json", expected)
    if (
        set(value)
        != {
            "schemaVersion",
            "runtime_image",
            "source_sha256",
            "code_manifest_sha256",
            "host_code_manifest_sha256",
        }
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or any(
            type(value[key]) is not str or not re.fullmatch(r"[a-f0-9]{64}", value[key])
            for key in (
                "source_sha256",
                "code_manifest_sha256",
                "host_code_manifest_sha256",
            )
        )
        or type(value["runtime_image"]) is not str
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", value["runtime_image"])
    ):
        raise RuntimeError("retirement_publisher_profile_invalid")
    if __package__:
        from .install import sources
    else:
        from install import sources
    sources(value["host_code_manifest_sha256"])
    return launch(PRIVATE, value["code_manifest_sha256"], image=value["runtime_image"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--profile-sha256", default="")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {"status": "prepared_only", "private_reads": 0, "Docker_actions": 0}
            )
        )
        return
    print(json.dumps({"status": execute(args.profile_sha256)}))


if __name__ == "__main__":
    main()
