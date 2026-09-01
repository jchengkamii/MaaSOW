"""自动帮助后台进程的 PID 身份记录。"""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259


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
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    return {"pid": pid, "created": created, "token": token}


def write_process_record(path: Path, pid: int, token: str) -> dict[str, object]:
    created = process_creation_time(pid)
    if created is None:
        raise RuntimeError(f"无法读取后台进程状态：pid={pid}")
    record: dict[str, object] = {"pid": pid, "created": created, "token": token}
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


def process_record_is_running(record: dict[str, object] | None) -> bool:
    if record is None:
        return False
    return process_creation_time(int(record["pid"])) == int(record["created"])
