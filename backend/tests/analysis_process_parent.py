"""A disposable parent lets tests prove Linux death signals without killing pytest."""

from pathlib import Path
import json
import subprocess
from analysis.process import ProcessEngine

actual = subprocess.Popen


def start(arguments, **options):
    index = arguments.index("-m")
    arguments = [
        *arguments[:index],
        str(Path(__file__).with_name("analysis_process_child.py")),
        *arguments[index + 2 :],
    ]
    process = actual(arguments, **options)
    print(json.dumps({"child_pid": process.pid}), flush=True)
    return process


subprocess.Popen = start
ProcessEngine().run({"question": "hold", "remaining_seconds": 10}, lambda stage: None)
