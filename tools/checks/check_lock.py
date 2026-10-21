"""Detect drift between the application's declared requirements and CI pins."""

from pathlib import Path
import re

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def main() -> None:
    """Check direct constraints; pip check validates the installed transitive graph."""
    root = Path(__file__).resolve().parents[2]
    lock = (root / "tools/checks/requirements-runtime.lock").read_text()
    pins = {
        canonicalize_name(name): version
        for name, version in re.findall(r"^([\w.-]+)==([^\s\\]+)", lock, re.MULTILINE)
    }
    for line in (root / "backend/requirements.txt").read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        requirement = Requirement(line)
        version = pins.get(canonicalize_name(requirement.name))
        if version is None or version not in requirement.specifier:
            raise SystemExit("refresh the CI lock for " + requirement.name)
    print("Runtime pins satisfy all direct requirement ranges.")


if __name__ == "__main__":
    main()
