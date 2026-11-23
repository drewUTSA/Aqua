"""Build the Windows presenter component from Aqua's tracked sources."""

import argparse
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
FILES = (
    "README.md",
    "run.py",
    "service.py",
    "tls_edge.py",
    "loopback.py",
    "model_cache.py",
    "profile_ca.py",
)


def build(destination):
    sources = [(name, HERE / name) for name in FILES]
    sources.append(
        ("bootstrap.psql", HERE.parents[1] / "backend/migrations/bootstrap.psql")
    )
    with zipfile.ZipFile(destination, "x") as archive:
        for name, path in sources:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    build(parser.parse_args().destination)
