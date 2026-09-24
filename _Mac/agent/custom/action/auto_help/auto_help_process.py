"""自动帮助后台进程的 PID 身份记录。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


import psutil
HEARTBEAT_TIMEOUT = 15.0


def process_creation_time(pid: int) -> int | None:
    if pid <= 0:
        return None
    try:
        process = psutil.Process(pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return None
        return round(process.create_time() * 1_000_000)
    except (psutil.Error, OSError):
        return None


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
    if not process_record_matches_process(record):
        return False
    try:
        process = psutil.Process(int(record["pid"]))
        if round(process.create_time() * 1_000_000) != int(record["created"]):
            return False
        process.terminate()
        try:
            process.wait(timeout=3)
        except psutil.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        return True
    except psutil.NoSuchProcess:
        return True
    except (psutil.Error, OSError):
        return False


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
