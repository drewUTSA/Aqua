"""Generate a short-lived trust root and leaf inside the disposable backend's tmpfs."""

from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import sys
import tarfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

host = sys.argv[1]
now = datetime.now(timezone.utc)
root_key = ec.generate_private_key(ec.SECP256R1())
leaf_key = ec.generate_private_key(ec.SECP256R1())
root_name = x509.Name(
    [x509.NameAttribute(NameOID.COMMON_NAME, "Aqua ephemeral demo root")]
)


def cert(name, key):
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(root_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=2))
        .not_valid_after(now + timedelta(hours=12))
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
            False,
        )
    )


root = (
    cert(root_name, root_key)
    .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
    .add_extension(
        x509.KeyUsage(False, False, False, False, False, True, True, False, False), True
    )
    .sign(root_key, hashes.SHA256())
)
leaf = (
    cert(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]), leaf_key)
    .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
    .add_extension(
        x509.KeyUsage(True, False, False, False, False, False, False, False, False),
        True,
    )
    .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
    .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), False)
    .sign(root_key, hashes.SHA256())
)
Path("/tmp/fixture-ca.pem").write_bytes(root.public_bytes(serialization.Encoding.PEM))
config = b"""worker_processes 1;
pid /tmp/fixture.pid;
error_log /dev/stderr crit;
events { worker_connections 64; }
http {
    access_log off;
    server {
        listen 127.0.0.1:8443 ssl;
        server_name _;
        ssl_certificate /tmp/fixture-leaf.pem;
        ssl_certificate_key /tmp/fixture-leaf.key;
        ssl_protocols TLSv1.2 TLSv1.3;
        location / {
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_pass http://127.0.0.1:5173;
        }
    }
}
"""
files = {
    "fixture-leaf.pem": leaf.public_bytes(serialization.Encoding.PEM),
    "fixture-leaf.key": leaf_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ),
    "edge.conf": config,
}
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
    for name, raw in files.items():
        member = tarfile.TarInfo(name)
        member.size, member.mode = len(raw), 0o600
        archive.addfile(member, io.BytesIO(raw))
