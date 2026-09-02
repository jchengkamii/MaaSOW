"""自动帮助后台进程的 PID 身份记录。"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
from pathlib import Path


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
STILL_ACTIVE = 259
HEARTBEAT_TIMEOUT = 15.0


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

    def as_int(self) -> int:
        return (self.high << 32) | self.low


def process_creation_time(pid: int) -> int | None:
    if os.name != "nt":
        return None
    process = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not process:
        return None
    try:
        exit_code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(
            process, ctypes.byref(exit_code)
        ) or exit_code.value != STILL_ACTIVE:
            return None
        created = _FileTime()
        exited = _FileTime()
        kernel = _FileTime()
        user = _FileTime()
        if not ctypes.windll.kernel32.GetProcessTimes(
            process,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        return created.as_int()
    finally:
        ctypes.windll.kernel32.CloseHandle(process)


def read_process_record(path: Path) -> dict[str, object] | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        pid = int(record["pid"])
        created = int(record["created"])
        token = str(record["token"])
        heartbeat = float(record.get("heartbeat", 0.0))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    return {
        "pid": pid,
        "created": created,
        "token": token,
        "heartbeat": heartbeat,
    }


def write_process_record(path: Path, pid: int, token: str) -> dict[str, object]:
    created = process_creation_time(pid)
    if created is None:
        raise RuntimeError(f"无法读取后台进程状态：pid={pid}")
    record: dict[str, object] = {
        "pid": pid,
        "created": created,
        "token": token,
        "heartbeat": time.time(),
    }
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


def process_record_matches_process(record: dict[str, object] | None) -> bool:
    if record is None:
        return False
    return process_creation_time(int(record["pid"])) == int(record["created"])


def process_record_is_running(
    record: dict[str, object] | None,
    heartbeat_timeout: float = HEARTBEAT_TIMEOUT,
) -> bool:
    if not process_record_matches_process(record):
        return False
    return time.time() - float(record["heartbeat"]) <= heartbeat_timeout


def touch_process_record(path: Path, pid: int, token: str) -> None:
    record = read_process_record(path)
    if (
        not process_record_matches_process(record)
        or int(record["pid"]) != pid
        or record["token"] != token
    ):
        return
    record["heartbeat"] = time.time()
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def terminate_recorded_process(record: dict[str, object] | None) -> bool:
    if os.name != "nt" or not process_record_matches_process(record):
        return False
    pid = int(record["pid"])
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            check=False,
        )
        if completed.returncode == 0 or not process_record_matches_process(record):
            return True
    except OSError:
        pass

    # taskkill 不可用时回退到 Win32 API。正常情况下 PID 记录的是实际
    # worker；这个回退仍能保证记录匹配后才终止，避免误伤复用 PID。
    process = ctypes.windll.kernel32.OpenProcess(
        PROCESS_TERMINATE, False, pid
    )
    if not process:
        return False
    try:
        return bool(ctypes.windll.kernel32.TerminateProcess(process, 1))
    finally:
        ctypes.windll.kernel32.CloseHandle(process)


def wait_for_recorded_process_exit(
    record: dict[str, object] | None, timeout: float = 3.0
) -> bool:
    """等待记录对应的进程退出，并持续校验创建时间以防 PID 复用。"""
    deadline = time.monotonic() + max(0.0, timeout)
    while process_record_matches_process(record):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True
