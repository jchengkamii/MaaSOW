from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from cases.auto_help.auto_help_process import (
    process_record_is_running,
    read_process_record,
    terminate_recorded_process,
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
    # 等 worker 自己登记实际 PID。不能立即写入 Popen.pid：Windows 虚拟
    # 环境的 python.exe 可能只是启动器，记录它会导致停止时留下真正的
    # 解释器子进程。
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        current = read_process_record(PID_PATH)
        if (
            current is not None
            and current.get("token") == launch_token
            and process_record_is_running(current)
        ):
            return f"自动帮助后台监视已启动，pid={int(current['pid'])}"
        if process.poll() is not None:
            raise RuntimeError(
                f"自动帮助后台进程启动失败，退出码={process.returncode}；"
                f"请查看 {LOG_PATH}"
            )
        time.sleep(0.05)

    if process.poll() is None:
        process.terminate()
    raise RuntimeError(f"自动帮助后台进程未能登记 PID；请查看 {LOG_PATH}")
