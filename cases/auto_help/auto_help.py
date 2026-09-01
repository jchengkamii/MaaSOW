from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

from cases.auto_help.auto_help_process import (
    process_record_is_running,
    read_process_record,
    terminate_recorded_process,
    write_process_record,
)


PROJECT_DIR = Path(__file__).resolve().parents[2]
WORKER_SCRIPT = Path(__file__).resolve().with_name("auto_help_worker.py")
PID_PATH = PROJECT_DIR / "cache" / "auto_help.pid"
LOG_PATH = PROJECT_DIR / "debug" / "auto_help.log"


def _existing_pid() -> int | None:
    record = read_process_record(PID_PATH)
    if not process_record_is_running(record):
        terminate_recorded_process(record)
        PID_PATH.unlink(missing_ok=True)
        return None
    return int(record["pid"])


def run(_engine, case) -> str:
    existing = _existing_pid()
    if existing is not None:
        return f"自动帮助已经在后台运行，pid={existing}"

    interval = float((case.parameters or {}).get("interval", 1.0))
    repeat_cooldown = float((case.parameters or {}).get("repeat_cooldown", 1.0))
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    launch_token = uuid.uuid4().hex
    environment["AUTO_HELP_LAUNCH_TOKEN"] = launch_token
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
    with LOG_PATH.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(WORKER_SCRIPT),
                "--interval",
                str(max(0.5, interval)),
                "--repeat-cooldown",
                str(max(1.0, repeat_cooldown)),
            ],
            cwd=PROJECT_DIR,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            startupinfo=startupinfo,
            close_fds=True,
        )
    # 虚拟环境启动器可能会转交给另一个解释器进程；工作进程若已登记实际
    # PID，此处不能再用启动器 PID 覆盖它。
    current = read_process_record(PID_PATH)
    if current is None or current.get("token") != launch_token:
        write_process_record(PID_PATH, process.pid, launch_token)
    return f"自动帮助后台监视已启动，pid={process.pid}"
