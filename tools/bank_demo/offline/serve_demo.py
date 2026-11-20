"""Launch the extracted synthetic server from any MCP host working directory."""

from pathlib import Path
import runpy
import sys

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    runpy.run_module("mcp_demo", run_name="__main__", alter_sys=True)
