from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[4]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from agent.core import AutomationEngine, CaseDefinition  # noqa: E402
from agent.custom.action.auto_help.automation_mutex import AutomationMutex  # noqa: E402
from agent.custom.action.auto_help.auto_help_process import (  # noqa: E402
    read_process_record,
    touch_process_record,
    write_process_record,
)


PID_PATH = PROJECT_DIR / "cache" / "auto_help.pid"


def _pipeline_case(case_id: str, entry: str) -> CaseDefinition:
    return CaseDefinition(
        id=case_id,
        name=case_id,
        group="后台辅助",
        description="",
        order=0,
        default_checked=False,
        enabled=True,
        handler="pipeline",
        pipeline_entry=entry,
        controller_target="game",
    )


def run(interval: float, repeat_cooldown: float) -> int:
    launch_token = os.environ.get("AUTO_HELP_LAUNCH_TOKEN", "")
    write_process_record(PID_PATH, os.getpid(), launch_token)
    engine = AutomationEngine(
        log=lambda message: print(f"[自动帮助] {message}", flush=True),
        framework_logging=False,
    )
    click_case = _pipeline_case("点击自动帮助", "点击自动帮助按钮")
    next_click_time = 0.0
    missing_window_count = 0

    engine.reload_resources()
    print(f"[自动帮助] 后台监视已启动，pid={os.getpid()}", flush=True)
    try:
        while True:
            touch_process_record(PID_PATH, os.getpid(), launch_token)
            if engine.find_window("game") is None:
                missing_window_count += 1
                if missing_window_count >= 15:
                    print("[自动帮助] 游戏窗口已关闭，后台监视退出", flush=True)
                    return 0
                time.sleep(2)
                continue
            missing_window_count = 0

            now = time.monotonic()
            if now < next_click_time:
                time.sleep(min(interval, next_click_time - now))
                continue

            mutex = AutomationMutex()
            if not mutex.acquire(timeout=0):
                mutex.close()
                time.sleep(interval)
                continue
            try:
                result = engine.execute_case(click_case)
                touch_process_record(PID_PATH, os.getpid(), launch_token)
                if result.status == "passed":
                    next_click_time = time.monotonic() + repeat_cooldown
                    print(
                        f"[自动帮助] 已点击一次，冷却 {repeat_cooldown:g} 秒后继续检测",
                        flush=True,
                    )
            finally:
                mutex.close()
            time.sleep(interval)
    finally:
        try:
            record = read_process_record(PID_PATH)
            if (
                record is not None
                and int(record["pid"]) == os.getpid()
                and record["token"] == launch_token
            ):
                PID_PATH.unlink(missing_ok=True)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="九霄仙府自动帮助后台监视")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--repeat-cooldown", type=float, default=1.0)
    args = parser.parse_args()
    return run(max(0.5, args.interval), max(1.0, args.repeat_cooldown))


if __name__ == "__main__":
    raise SystemExit(main())
