from __future__ import annotations

from pathlib import Path

from cases.auto_help.auto_help_process import (
    process_record_matches_process,
    read_process_record,
    terminate_recorded_process,
    wait_for_recorded_process_exit,
)


PROJECT_DIR = Path(__file__).resolve().parents[2]
PID_PATH = PROJECT_DIR / "cache" / "auto_help.pid"


def run(_engine, _case) -> str:
    record = read_process_record(PID_PATH)
    if not process_record_matches_process(record):
        PID_PATH.unlink(missing_ok=True)
        return "自动帮助当前未运行"

    assert record is not None
    pid = int(record["pid"])
    if not terminate_recorded_process(record):
        raise RuntimeError(
            f"无法停止自动帮助进程 pid={pid}；请确认前台与后台进程权限一致"
        )
    if not wait_for_recorded_process_exit(record):
        raise RuntimeError(f"停止自动帮助进程超时：pid={pid}")

    PID_PATH.unlink(missing_ok=True)
    return f"自动帮助已停止，pid={pid}"
