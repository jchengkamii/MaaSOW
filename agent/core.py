from __future__ import annotations

import json
import importlib
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

PROJECT_DIR = Path(__file__).resolve().parents[1]
CUSTOM_ACTION_DIR = PROJECT_DIR / "agent" / "custom" / "action"
RESOURCE_DIR = PROJECT_DIR / "resource" / "base"
TASKS_DIR = PROJECT_DIR / "resource" / "tasks"
RUNTIME_DIR = PROJECT_DIR.parent / ".maafw_runtime"

if sys.version_info[:2] != (3, 12):
    raise RuntimeError(
        "当前项目必须使用 Python 3.12；"
        f"实际运行版本为 {sys.version_info.major}.{sys.version_info.minor}。\n"
        rf"请使用：{PROJECT_DIR / '.venv' / 'Scripts' / 'python.exe'}"
    )

sys.path.insert(0, str(RUNTIME_DIR))

from maa.controller import (  # noqa: E402
    MaaWin32InputMethodEnum,
    MaaWin32ScreencapMethodEnum,
    Win32Controller,
)
from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402
from maa.toolkit import Toolkit  # noqa: E402


LogCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class CaseDefinition:
    id: str
    name: str
    group: str
    description: str
    order: int
    default_checked: bool
    enabled: bool
    handler: str
    pipeline_entry: str | None = None
    controller_target: str | None = None
    wait_for_window: str | None = None
    wait_timeout: float = 30.0
    skip_if_window_exists: str | None = None
    postcondition_entry: str | None = None
    postcondition_target: str | None = None
    postcondition_timeout: float = 120.0
    extension: str | None = None
    parameters: dict | None = None
    source: Path | None = None


@dataclass(frozen=True, slots=True)
class CaseResult:
    status: str
    message: str
    elapsed: float


class CaseConfigError(ValueError):
    pass


class CaseLoader:
    REQUIRED_FIELDS = {"id", "name", "handler"}
    ALLOWED_HANDLERS = {"ensure_miniprogram_panel", "pipeline", "python"}
    ALLOWED_TARGETS = {"wechat_main", "wechat_panel", "game"}

    def __init__(self, tasks_dir=TASKS_DIR):
        self.tasks_dir = tasks_dir

    def load(self) -> list[CaseDefinition]:
        if not self.tasks_dir.exists():
            raise CaseConfigError(f"任务清单目录不存在：{self.tasks_dir}")

        cases: list[CaseDefinition] = []
        seen_ids: set[str] = set()
        for path in sorted(self.tasks_dir.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CaseConfigError(f"无法读取用例 {path.name}：{exc}") from exc

            if not isinstance(data, dict):
                raise CaseConfigError(f"用例必须是 JSON 对象：{path.name}")
            if data.get("version") != 1:
                raise CaseConfigError(f"用例 {path.name} 的 version 必须为 1")
            missing = self.REQUIRED_FIELDS - data.keys()
            if missing:
                raise CaseConfigError(
                    f"用例 {path.name} 缺少字段：{', '.join(sorted(missing))}"
                )

            case_id = str(data["id"]).strip()
            if not case_id:
                raise CaseConfigError(f"用例 id 不能为空：{path.name}")
            if path.stem != case_id:
                raise CaseConfigError(
                    f"任务清单文件名必须与 id 一致：{path.name} != {case_id}.json"
                )
            if case_id in seen_ids:
                raise CaseConfigError(f"用例 id 重复：{case_id}")
            seen_ids.add(case_id)

            handler = str(data["handler"]).strip()
            if handler not in self.ALLOWED_HANDLERS:
                raise CaseConfigError(f"用例 {case_id} 使用未知 handler：{handler}")

            pipeline_entry = data.get("pipeline_entry")
            controller_target = data.get("controller_target")
            if handler == "pipeline":
                if not pipeline_entry:
                    raise CaseConfigError(f"Pipeline 用例 {case_id} 缺少 pipeline_entry")
                if controller_target not in self.ALLOWED_TARGETS:
                    raise CaseConfigError(
                        f"Pipeline 用例 {case_id} 的 controller_target 无效："
                        f"{controller_target}"
                    )
            extension = data.get("extension")
            if handler == "python" and (
                not isinstance(extension, str) or ":" not in extension
            ):
                raise CaseConfigError(
                    f"Python 用例 {case_id} 的 extension 必须使用 module:function 格式"
                )
            parameters = data.get("parameters", {})
            if not isinstance(parameters, dict):
                raise CaseConfigError(f"用例 {case_id} 的 parameters 必须是 JSON 对象")
            postcondition_entry = data.get("postcondition_entry")
            postcondition_target = data.get("postcondition_target")
            if postcondition_entry and postcondition_target not in self.ALLOWED_TARGETS:
                raise CaseConfigError(
                    f"用例 {case_id} 的 postcondition_target 无效："
                    f"{postcondition_target}"
                )

            cases.append(
                CaseDefinition(
                    id=case_id,
                    name=str(data["name"]).strip(),
                    group=str(data.get("group", "未分组")).strip() or "未分组",
                    description=str(data.get("description", "")).strip(),
                    order=int(data.get("order", 1000)),
                    default_checked=bool(data.get("default_checked", False)),
                    enabled=bool(data.get("enabled", True)),
                    handler=handler,
                    pipeline_entry=(str(pipeline_entry) if pipeline_entry else None),
                    controller_target=(
                        str(controller_target) if controller_target else None
                    ),
                    wait_for_window=(
                        str(data["wait_for_window"])
                        if data.get("wait_for_window")
                        else None
                    ),
                    wait_timeout=float(data.get("wait_timeout", 30)),
                    skip_if_window_exists=(
                        str(data["skip_if_window_exists"])
                        if data.get("skip_if_window_exists")
                        else None
                    ),
                    postcondition_entry=(
                        str(postcondition_entry) if postcondition_entry else None
                    ),
                    postcondition_target=(
                        str(postcondition_target) if postcondition_target else None
                    ),
                    postcondition_timeout=float(data.get("postcondition_timeout", 120)),
                    extension=(str(extension) if extension else None),
                    parameters=parameters,
                    source=path,
                )
            )

        cases.sort(key=lambda item: (item.order, item.id))
        return cases


class AutomationEngine:
    # Maa 将 Win32 截图短边归一化为 720；该坐标对应当前微信左栏的小程序按钮。
    MINIPROGRAM_BUTTON = (34, 440)
    WINDOW_SPECS = {
        "wechat_main": ("微信", "Qt51514QWindowIcon"),
        "wechat_panel": ("微信", "Chrome_WidgetWin_0"),
        "game": ("九霄仙府", "Chrome_WidgetWin_0"),
    }

    def __init__(
        self,
        log: LogCallback | None = None,
        framework_logging: bool = True,
    ):
        self.log = log or (lambda _message: None)
        self.stop_event = threading.Event()
        self._state_lock = threading.RLock()
        self._current_tasker: Tasker | None = None
        self._resource: Resource | None = None
        self._controllers: dict[str, tuple[int, Win32Controller]] = {}
        Toolkit.init_option(
            PROJECT_DIR,
            {
                "logging": framework_logging,
                "save_draw": False,
                "save_on_error": False,
                "stdout_level": 2,
            },
        )

    def reload_resources(self) -> None:
        if self._current_tasker is not None:
            raise RuntimeError("任务执行期间不能刷新资源")
        self.log("正在加载 Maa Pipeline 和图片模板……")
        resource = Resource()
        job = resource.post_bundle(RESOURCE_DIR).wait()
        if not job.succeeded:
            raise RuntimeError(f"加载 Maa 资源失败：{RESOURCE_DIR}")
        with self._state_lock:
            self._resource = resource
        self.log("Maa 资源加载完成")

    def reset_stop(self) -> None:
        self.stop_event.clear()

    def request_stop(self) -> None:
        self.stop_event.set()
        with self._state_lock:
            tasker = self._current_tasker
        if tasker is not None:
            try:
                tasker.post_stop().wait()
            except Exception as exc:  # 停止仍以 stop_event 为兜底。
                self.log(f"停止 Maa 任务时出现提示：{exc}")

    def find_window(self, target: str):
        if target not in self.WINDOW_SPECS:
            raise RuntimeError(f"未知窗口目标：{target}")
        title, class_name = self.WINDOW_SPECS[target]
        for window in Toolkit.find_desktop_windows():
            if (
                window.window_name.strip() == title
                and window.class_name.strip() == class_name
            ):
                return window
        return None

    def connection_status(self) -> dict[str, bool]:
        return {
            target: self.find_window(target) is not None
            for target in self.WINDOW_SPECS
        }

    def _controller_for(self, target: str) -> Win32Controller:
        window = self.find_window(target)
        if window is None:
            title, _class_name = self.WINDOW_SPECS[target]
            raise RuntimeError(f"没有找到窗口：{title}（{target}）")

        cached = self._controllers.get(target)
        if cached is not None and cached[0] == window.hwnd:
            return cached[1]

        mouse_method, keyboard_method = self._input_methods_for(target)
        controller = Win32Controller(
            hWnd=window.hwnd,
            screencap_method=MaaWin32ScreencapMethodEnum.Background,
            mouse_method=mouse_method,
            keyboard_method=keyboard_method,
        )
        if not controller.post_connection().wait().succeeded:
            raise RuntimeError(f"连接窗口失败：{window.window_name}")
        self._controllers[target] = (window.hwnd, controller)
        self.log(f"已连接窗口：{window.window_name}，hwnd={window.hwnd}")
        return controller

    @staticmethod
    def _input_methods_for(target: str):
        if target == "game":
            return (
                MaaWin32InputMethodEnum.SendMessage,
                MaaWin32InputMethodEnum.PostMessage,
            )
        return (MaaWin32InputMethodEnum.Seize, MaaWin32InputMethodEnum.Seize)

    def _wait_for_window(self, target: str, timeout: float):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                raise InterruptedError("用户停止执行")
            window = self.find_window(target)
            if window is not None:
                return window
            time.sleep(0.5)
        title, _class_name = self.WINDOW_SPECS.get(target, (target, ""))
        raise RuntimeError(f"等待窗口超时：{title}")

    def _ensure_miniprogram_panel(self) -> str:
        if self.find_window("game") is not None:
            return "游戏已经打开，无需打开小程序面板"
        if self.find_window("wechat_panel") is not None:
            return "微信小程序面板已经打开"

        controller = self._controller_for("wechat_main")
        controller.post_screencap().wait()
        if not controller.post_click(*self.MINIPROGRAM_BUTTON).wait().succeeded:
            raise RuntimeError("点击微信小程序按钮失败")
        self._wait_for_window("wechat_panel", 8)
        return "微信小程序面板已打开"

    def _run_pipeline(self, case: CaseDefinition) -> str:
        skip_initial = bool(
            case.skip_if_window_exists
            and self.find_window(case.skip_if_window_exists) is not None
        )

        if not skip_initial and case.controller_target == "wechat_panel":
            self._ensure_miniprogram_panel()

        with self._state_lock:
            resource = self._resource
        if resource is None:
            self.reload_resources()
            with self._state_lock:
                resource = self._resource
        if resource is None:
            raise RuntimeError("Maa Resource 未初始化")

        if not skip_initial:
            self._execute_pipeline_entry(
                case.controller_target or "game", case.pipeline_entry or "", resource
            )
        else:
            title, _class_name = self.WINDOW_SPECS[case.skip_if_window_exists or "game"]
            self.log(f"{title}窗口已经存在，跳过重复打开操作")

        postcondition_deadline = (
            time.monotonic() + case.postcondition_timeout
            if case.postcondition_entry
            else None
        )

        if case.wait_for_window:
            wait_timeout = case.wait_timeout
            if postcondition_deadline is not None:
                wait_timeout = min(
                    wait_timeout, max(0.1, postcondition_deadline - time.monotonic())
                )
            self._wait_for_window(case.wait_for_window, wait_timeout)
        if case.postcondition_entry:
            target = case.postcondition_target or case.wait_for_window or "game"
            remaining = max(
                0.0, (postcondition_deadline or time.monotonic()) - time.monotonic()
            )
            if remaining <= 0:
                raise RuntimeError(
                    f"等待主界面超时（{case.postcondition_timeout:.0f} 秒）"
                )
            self.log(
                f"等待后置断言：{case.postcondition_entry}，剩余 {remaining:.1f} 秒"
            )
            self._execute_pipeline_entry(
                target,
                case.postcondition_entry,
                resource,
                timeout_override=remaining,
            )
        if skip_initial:
            if case.postcondition_entry:
                return f"游戏窗口已存在，主界面断言成功：{case.postcondition_entry}"
            return "游戏窗口已存在，跳过重复打开操作"
        if case.postcondition_entry:
            return f"Pipeline 执行成功：{case.pipeline_entry}；主界面加载完成"
        if case.wait_for_window:
            title, _class_name = self.WINDOW_SPECS[case.wait_for_window]
            return f"Pipeline 执行成功：{case.pipeline_entry}；{title}窗口已出现"
        return f"Pipeline 执行成功：{case.pipeline_entry}"

    def _execute_pipeline_entry(
        self,
        target: str,
        entry: str,
        resource: Resource,
        timeout_override: float | None = None,
    ) -> None:
        controller = self._controller_for(target)
        tasker = Tasker()
        tasker.bind(resource, controller)
        if not tasker.inited:
            raise RuntimeError("Maa Tasker 初始化失败")

        with self._state_lock:
            self._current_tasker = tasker
        try:
            pipeline_override = None
            if timeout_override is not None:
                pipeline_override = {
                    entry: {"timeout": max(1, int(timeout_override * 1000))}
                }
            job = tasker.post_task(entry, pipeline_override).wait()
            if self.stop_event.is_set():
                raise InterruptedError("用户停止执行")
            if not job.succeeded:
                raise RuntimeError(f"Maa Pipeline 执行失败：{entry}")
        finally:
            with self._state_lock:
                self._current_tasker = None


    def _run_python_extension(self, case: CaseDefinition) -> str:
        if not case.extension:
            raise RuntimeError(f"Python 用例没有配置 extension：{case.id}")
        module_name, function_name = case.extension.split(":", 1)
        importlib.invalidate_caches()
        module = importlib.import_module(module_name)
        function = getattr(module, function_name, None)
        if not callable(function):
            raise RuntimeError(f"扩展入口不可调用：{case.extension}")
        result = function(self, case)
        return str(result) if result is not None else f"扩展执行成功：{case.extension}"

    def execute_case(self, case: CaseDefinition) -> CaseResult:
        started = time.monotonic()
        try:
            if self.stop_event.is_set():
                raise InterruptedError("用户停止执行")
            if not case.enabled:
                return CaseResult("skipped", "用例已禁用", 0.0)
            if case.handler == "ensure_miniprogram_panel":
                message = self._ensure_miniprogram_panel()
            elif case.handler == "pipeline":
                message = self._run_pipeline(case)
            elif case.handler == "python":
                message = self._run_python_extension(case)
            else:
                raise RuntimeError(f"未知用例处理器：{case.handler}")
            return CaseResult("passed", message, time.monotonic() - started)
        except InterruptedError as exc:
            return CaseResult("stopped", str(exc), time.monotonic() - started)
        except Exception as exc:
            return CaseResult("failed", str(exc), time.monotonic() - started)

    def execute_cases(
        self,
        cases: Iterable[CaseDefinition],
        on_case_start: Callable[[CaseDefinition], None] | None = None,
        on_case_end: Callable[[CaseDefinition, CaseResult], None] | None = None,
    ) -> list[tuple[CaseDefinition, CaseResult]]:
        self.reset_stop()
        results: list[tuple[CaseDefinition, CaseResult]] = []
        for case in cases:
            if self.stop_event.is_set():
                break
            if on_case_start:
                on_case_start(case)
            result = self.execute_case(case)
            results.append((case, result))
            if on_case_end:
                on_case_end(case, result)
            if result.status in {"failed", "stopped"}:
                break
        return results
