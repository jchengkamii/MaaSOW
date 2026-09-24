from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[3]
WORKER_SCRIPT = PROJECT_DIR / "agent" / "worker.py"
RESULT_PREFIX = "__MXU_CASE_RESULT__="

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from maa.agent.agent_server import AgentServer  # noqa: E402
from maa.context import Context  # noqa: E402
from maa.custom_action import CustomAction  # noqa: E402


def parse_case_id(raw: str) -> str:
    return parse_case_request(raw)[0]


def parse_case_request(raw: str) -> tuple[str, int | None]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    target_minutes = None
    if isinstance(value, dict):
        raw_minutes = value.get("target_minutes")
        if raw_minutes is not None:
            try:
                target_minutes = int(raw_minutes)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("治疗目标分钟数必须是整数") from exc
            if not 1 <= target_minutes <= 10000:
                raise RuntimeError("治疗目标分钟数必须在 1–10000 之间")
        value = value.get("case_id", "")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"无效的用例参数：{raw!r}")
    return value.strip(), target_minutes


def parse_attack_count(raw: str) -> int | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or "attack_count" not in value:
        return None
    from agent.custom.action.auto_pixiu import attack_count
    if value.get("case_id") != "auto_pixiu":
        raise ValueError("进攻次数参数只能用于自动打貔貅")
    return attack_count(value["attack_count"])


def parse_rally_options(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    options = {key: value[key] for key in ("rally_level", "rally_count") if key in value}
    if options:
        if value.get("case_id") != "auto_ling_er":
            raise ValueError("集结参数只能用于自动玲儿降妖")
        from agent.custom.action.auto_ling_er import rally_level, attack_count
        options = {key: (rally_level(val) if key == "rally_level" else attack_count(val))
                   for key, val in options.items()}
    return options


def worker_command(case_id: str) -> list[str]:
    return worker_command_with_options(case_id, auto_stamina=False)


def worker_command_with_options(
    case_id: str, auto_stamina: bool, target_minutes: int | None = None,
    attack_count: int | None = None,
    rally_level: int | None = None, rally_count: int | None = None,
    rally_queues: list[int] | None = None
) -> list[str]:
    command = [sys.executable, "-u", "-m", "agent.worker", "--case-id", case_id]
    if auto_stamina:
        command.append("--auto-stamina")
    if target_minutes is not None:
        command.extend(["--target-minutes", str(target_minutes)])
    if attack_count is not None:
        command.extend(["--attack-count", str(attack_count)])
    for key, value in (("rally-level", rally_level), ("rally-count", rally_count)):
        if value is not None:
            command.extend([f"--{key}", str(value)])
    if rally_queues is not None:
        command.extend(["--rally-queues", ",".join(map(str, rally_queues))])
    return command


def selected_rally_queues(context: Context) -> list[int]:
    from agent.custom.action.auto_ling_er import rally_queues
    return rally_queues([q for q in range(1, 5)
                         if (context.get_node_data(f"玲儿集结队列{q}") or {}).get("enabled") is True])


def auto_stamina_enabled(context: Context) -> bool:
    node = context.get_node_data("通用自动补体开关") or {}
    return node.get("enabled") is True


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


@AgentServer.custom_action("RunConfiguredCase")
class RunConfiguredCase(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        try:
            case_id, target_minutes = parse_case_request(argv.custom_action_param)
            attack_count = parse_attack_count(argv.custom_action_param)
            rally_options = parse_rally_options(argv.custom_action_param)
            if case_id == "auto_ling_er":
                rally_options["rally_queues"] = selected_rally_queues(context)
        except Exception as exc:
            print(f"[Agent] 用例参数错误：{exc}", flush=True)
            return False

        use_auto_stamina = auto_stamina_enabled(context)

        if not WORKER_SCRIPT.is_file():
            print(f"[Agent] 找不到用例工作进程脚本：{WORKER_SCRIPT}", flush=True)
            return False

        suffix_parts = []
        if attack_count is not None:
            suffix_parts.append(f"进攻 {attack_count} 次")
        if use_auto_stamina:
            suffix_parts.append("自动补体已启用")
        if target_minutes is not None:
            suffix_parts.append(f"治疗目标 {target_minutes} 分钟")
        suffix = f"（{'；'.join(suffix_parts)}）" if suffix_parts else ""
        print(f"[Agent] 提交独立工作进程：{case_id}{suffix}", flush=True)
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(
                worker_command_with_options(
                    case_id, use_auto_stamina, target_minutes, attack_count, **rally_options
                ),
                cwd=PROJECT_DIR,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except Exception as exc:
            print(f"[Agent] 无法启动用例工作进程：{exc}", flush=True)
            return False

        output_queue: queue.Queue[str] = queue.Queue()

        def read_output() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                output_queue.put(line.rstrip("\r\n"))

        reader = threading.Thread(
            target=read_output,
            daemon=True,
            name=f"case-output-{case_id}",
        )
        reader.start()

        result_payload: dict[str, object] | None = None
        stopped = False

        def drain_output() -> None:
            nonlocal result_payload
            while True:
                try:
                    line = output_queue.get_nowait()
                except queue.Empty:
                    return
                if not line.startswith(RESULT_PREFIX):
                    print(line, flush=True)
                    continue
                try:
                    value = json.loads(line[len(RESULT_PREFIX) :])
                    if isinstance(value, dict):
                        result_payload = value
                except json.JSONDecodeError as exc:
                    print(f"[Agent] 无法解析工作进程结果：{exc}", flush=True)

        try:
            while process.poll() is None:
                drain_output()
                if context.tasker.stopping:
                    stopped = True
                    print(f"[Agent] 正在停止用例：{case_id}", flush=True)
                    _stop_process(process)
                    break
                time.sleep(0.1)
            reader.join(timeout=2)
            drain_output()
        finally:
            if process.poll() is None:
                _stop_process(process)

        if stopped:
            return False
        if result_payload is None:
            print(
                f"[Agent] 用例工作进程没有返回结果：{case_id}；"
                f"退出码 {process.returncode}",
                flush=True,
            )
            return False

        status = str(result_payload.get("status", "failed"))
        message = str(result_payload.get("message", "未提供执行结果"))
        elapsed = float(result_payload.get("elapsed", 0.0))
        name = str(result_payload.get("name", case_id))
        print(
            f"[Agent] {name}：{status}；{message}；耗时 {elapsed:.2f}s",
            flush=True,
        )
        return process.returncode == 0 and status in {"passed", "skipped"}
