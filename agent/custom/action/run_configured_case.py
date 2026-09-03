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
RUNTIME_DIR = PROJECT_DIR.parent / ".maafw_runtime"
WORKER_SCRIPT = PROJECT_DIR / "agent" / "worker.py"
RESULT_PREFIX = "__MXU_CASE_RESULT__="

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from maa.agent.agent_server import AgentServer  # noqa: E402
from maa.context import Context  # noqa: E402
from maa.custom_action import CustomAction  # noqa: E402


def parse_case_id(raw: str) -> str:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    if isinstance(value, dict):
        value = value.get("case_id", "")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"无效的用例参数：{raw!r}")
    return value.strip()


def worker_command(case_id: str) -> list[str]:
    return worker_command_with_options(case_id, auto_stamina=False)


def worker_command_with_options(case_id: str, auto_stamina: bool) -> list[str]:
    command = [sys.executable, "-u", "-m", "agent.worker", "--case-id", case_id]
    if auto_stamina:
        command.append("--auto-stamina")
    return command


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
            case_id = parse_case_id(argv.custom_action_param)
        except Exception as exc:
            print(f"[Agent] 用例参数错误：{exc}", flush=True)
            return False

        use_auto_stamina = auto_stamina_enabled(context)

        if not WORKER_SCRIPT.is_file():
            print(f"[Agent] 找不到用例工作进程脚本：{WORKER_SCRIPT}", flush=True)
            return False

        suffix = "（自动补体已启用）" if use_auto_stamina else ""
        print(f"[Agent] 提交独立工作进程：{case_id}{suffix}", flush=True)
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(
                worker_command_with_options(case_id, use_auto_stamina),
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
