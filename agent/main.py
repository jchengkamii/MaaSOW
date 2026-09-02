from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_DIR.parent / ".maafw_runtime"
DEBUG_DIR = PROJECT_DIR / "debug"

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from maa.agent.agent_server import AgentServer  # noqa: E402
from maa.tasker import Tasker  # noqa: E402

# Importing the module registers its decorated custom action.
from agent.custom.action import run_configured_case  # noqa: E402, F401


def main() -> int:
    Tasker.set_log_dir(str(DEBUG_DIR))
    if len(sys.argv) < 2:
        print("Usage: agent/main.py <socket_id>", flush=True)
        return 2
    socket_id = sys.argv[-1]
    AgentServer.start_up(socket_id)
    try:
        AgentServer.join()
    finally:
        AgentServer.shut_down()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
