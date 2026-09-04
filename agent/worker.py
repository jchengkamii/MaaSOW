from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace

from agent.core import AutomationEngine, CaseLoader
from agent.custom.action.auto_help.automation_mutex import AutomationMutex


RESULT_PREFIX = "__MXU_CASE_RESULT__="


def _emit_result(payload: dict[str, object]) -> None:
    print(
        RESULT_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        flush=True,
    )


def execute(
    case_id: str,
    auto_stamina: bool = False,
    target_minutes: int | None = None,
) -> int:
    started = time.monotonic()
    try:
        cases = {case.id: case for case in CaseLoader().load()}
        case = cases.get(case_id)
        if case is None:
            raise RuntimeError(f"未找到外部用例：{case_id}")
        if target_minutes is not None:
            if case.id != "auto_treatment":
                raise RuntimeError("治疗时长参数只能用于自动治疗")
            if not 1 <= target_minutes <= 10000:
                raise RuntimeError("治疗目标分钟数必须在 1–10000 之间")
            parameters = dict(case.parameters or {})
            parameters["target_seconds"] = target_minutes * 60
            case = replace(case, parameters=parameters)

        print(f"[Worker] 开始执行：{case.name}", flush=True)
        engine = AutomationEngine(
            log=lambda message: print(f"[Worker] {message}", flush=True),
            auto_stamina=auto_stamina,
        )
        engine.reset_stop()
        # 长驻协作用例会在真正操作游戏时自行加锁，并在等待阶段释放锁，
        # 让自动帮助等后台任务获得执行窗口。
        if bool((case.parameters or {}).get("cooperative_mutex", False)):
            result = engine.execute_case(case)
        else:
            with AutomationMutex():
                result = engine.execute_case(case)
        payload: dict[str, object] = {
            "case_id": case.id,
            "name": case.name,
            "status": result.status,
            "message": result.message,
            "elapsed": result.elapsed,
        }
    except Exception as exc:
        payload = {
            "case_id": case_id,
            "name": case_id,
            "status": "failed",
            "message": str(exc),
            "elapsed": time.monotonic() - started,
        }

    _emit_result(payload)
    return 0 if payload["status"] in {"passed", "skipped"} else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="在独立 MaaFramework 进程中执行一个用例")
    parser.add_argument("--case-id", required=True, help="cases 目录中的用例 ID")
    parser.add_argument(
        "--auto-stamina",
        action="store_true",
        help="行军体力不足时执行通用自动补体流程",
    )
    parser.add_argument(
        "--target-minutes",
        type=int,
        help="自动治疗的单批目标分钟数",
    )
    args = parser.parse_args()
    return execute(
        args.case_id.strip(),
        auto_stamina=args.auto_stamina,
        target_minutes=args.target_minutes,
    )


if __name__ == "__main__":
    raise SystemExit(main())
