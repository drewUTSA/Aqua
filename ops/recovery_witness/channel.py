"""Authenticated one-record exchange between the signer host and its witness."""

import hashlib
import struct

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from retirement.publisher import FRAME_BYTES, RECEIPT, REQUEST


def respond(journal, generation, service_public_key, witness_key, request):
    """The append-only service has no way to set/inspect/remove the owner fence."""
    if type(request) is not bytes or len(request) != FRAME_BYTES:
        raise ValueError("checkpoint_witness_request_size")
    body = request[:-64]
    if struct.unpack("!Q", body[:8])[0] != generation:
        raise ValueError("checkpoint_witness_publisher_generation")
    Ed25519PublicKey.from_public_bytes(service_public_key).verify(
        request[-64:], REQUEST + body
    )
    journal.append(generation, body[40:], service_public_key=service_public_key)
    return witness_key.sign(RECEIPT + hashlib.sha256(request).digest())
