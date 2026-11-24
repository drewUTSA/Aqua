"""Operate an explicitly provisioned retirement witness on the recovery PC."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from retirement.checkpoint import RECORD_BYTES

if __package__:
    from .journal import Identity, Witness
else:
    from journal import Identity, Witness


def read_profile(path, expected_sha):
    import hashlib
    import hmac

    with path.open("rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096 or not hmac.compare_digest(
        hashlib.sha256(raw).hexdigest(), expected_sha
    ):
        raise ValueError("checkpoint_witness_profile_pin")

    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("checkpoint_witness_duplicate_profile_key")
            result[key] = value
        return result

    data = json.loads(raw, object_pairs_hook=unique)
    if type(data) is not dict or set(data) != {
        "installation_id",
        "identity_key_id",
        "key_commitment",
        "public_key",
    }:
        raise ValueError("checkpoint_witness_public_identity")
    return Identity(
        data["installation_id"],
        data["identity_key_id"],
        bytes.fromhex(data["key_commitment"]),
        bytes.fromhex(data["public_key"]),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--profile-sha256", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    enroll = commands.add_parser("enroll")
    enroll.add_argument("--service-public-key", required=True)
    for name in ("fence", "inspect-fence"):
        command = commands.add_parser(name)
        command.add_argument("--generation", required=True, type=int)
        command.add_argument("--fence-id", required=True)
    args = parser.parse_args(argv)
    identity = read_profile(args.profile, args.profile_sha256)
    witness = Witness(args.profile.with_name("checkpoint.sqlite3"), identity)
    if args.command == "enroll":
        raw = sys.stdin.buffer.read(RECORD_BYTES + 1)
        receipt = witness.enroll(
            raw, service_public_key=bytes.fromhex(args.service_public_key)
        )
        result = {"committed_record_sha256": receipt.hex()}
    else:
        read = witness.fence if args.command == "fence" else witness.frozen_head
        cut = read(args.generation, args.fence_id)
        result = {
            "generation": cut.generation,
            "fence_id": cut.fence_id,
            "sequence": cut.sequence,
            "signed_head": cut.head.hex(),
            "chain_sha256": cut.chain_sha256,
        }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
