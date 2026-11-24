"""Hold the independent fence across offline restore and retirement reconciliation."""

from contextlib import contextmanager

from ops.retirement.backup_client.vendor import authority_archive
from .journal import WitnessUnavailable


@contextmanager
def recovery_archive(
    witness, generation, fence_id, authority_bytes, *, runtime_image, schema_sha256
):
    """Verify receipt, pinned code/schema, keys and history before touching the target.

    The controller supplies offline decrypted bytes and independently selected
    source pins. Its target must remain isolated with writers stopped, including
    after failures. Neither success nor cleanup automatically resumes publishing.
    """
    latest = witness.frozen_head(generation, fence_id)
    archive = authority_archive.read(authority_bytes, latest.head)
    identity = witness.identity
    pins = {
        "installation_id": identity.installation,
        "identity_key_id": identity.key_id,
        "key_commitment": identity.commitment.hex(),
        "public_key": identity.public_key.hex(),
        "runtime_image": runtime_image,
        "source_sha256": schema_sha256,
    }
    if any(archive.profile.get(k) != v for k, v in pins.items()):
        raise WitnessUnavailable("checkpoint_witness_archive_identity_or_source")
    with witness.recovery_cut(
        generation, fence_id, archive.contents["checkpoints.bin"]
    ) as cut:
        yield cut, archive
