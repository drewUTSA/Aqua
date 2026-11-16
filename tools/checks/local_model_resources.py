"""A separately bounded model runner; canonical regression fixture limits stay intact."""

import subprocess
from unittest.mock import patch

import run_backend
from run_backend import POSTGRES, create, docker, provision_core


def provision_model(image, run_name, containers, archive):
    # Inspection before creation plus --pull=never also closes a removal race.
    actual = docker("image", "inspect", image, "--format", "{{.Id}}").decode().strip()
    if actual != image:
        raise ValueError("runtime_image_identity_invalid")
    docker("image", "inspect", POSTGRES, "--format", "{{.Id}}")

    def local_create(name, selected_image, *args, command=()):
        return create(name, selected_image, "--pull=never", *args, command=command)

    # A scoped adapter adds a restriction; canonical fixtures and their limits
    # are not edited or widened by this model-only harness.
    with patch.object(run_backend, "create", local_create):
        pg, original = provision_core(
            image=image, run_name=run_name, containers=containers, archive=archive
        )
    # The canonical runner has a 300s lifetime. Remove it, prove absence, then
    # create this experiment's own runner rather than changing that contract.
    docker("rm", "--force", original)
    absence = subprocess.run(
        ["docker", "container", "inspect", original], capture_output=True, timeout=15
    )
    if absence.returncode != 1 or b"No such" not in absence.stderr:
        raise RuntimeError("original_runner_absence_unverified")
    containers.remove(original)
    runner = local_create(
        run_name + "-model",
        image,
        "--network=container:" + pg,
        "--user=1000:1000",
        "--tmpfs=/tmp:rw,nosuid,nodev,size=268435456,mode=1777",
        "--tmpfs=/checks:rw,nosuid,nodev,size=67108864,mode=0777",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
        "-e",
        "PYTHON_DOTENV_DISABLED=1",
        "--workdir=/tmp",
        "--entrypoint=/bin/sleep",
        command=("1080",),
    )
    containers.append(runner)
    docker("start", runner)
    unpack = "import io,sys,tarfile;tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())).extractall('/checks',filter='data')"
    docker("exec", "-i", runner, "python", "-c", unpack, data=archive)
    return runner
