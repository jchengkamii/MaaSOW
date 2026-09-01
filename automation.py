from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = PROJECT_DIR.parent / ".maafw_runtime"

# 当前本地 MaaFw 运行时中的 NumPy/DLL 使用 CPython 3.12 ABI。
# 在 3.13 等解释器中加载会出现 numpy C-extension 导入失败。
if sys.version_info[:2] != (3, 12):
    raise RuntimeError(
        "当前项目必须使用 Python 3.12；"
        f"实际运行版本为 {sys.version_info.major}.{sys.version_info.minor}。\n"
        rf"请在 PyCharm 中选择解释器：{PROJECT_DIR / '.venv' / 'Scripts' / 'python.exe'}"
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


ASSET_CROPS = (
    (
        PROJECT_DIR / "debug" / "wechat-miniprogram-panel.png",
        PROJECT_DIR / "resource" / "image" / "wechat" / "jiuxiao_xianfu_entry.png",
        (120, 135, 190, 215),
    ),
    (
        PROJECT_DIR / "debug" / "jiuxiao-game.png",
        PROJECT_DIR / "resource" / "image" / "game" / "avatar_button.png",
        (12, 62, 100, 155),
    ),
    (
        PROJECT_DIR / "debug" / "jiuxiao-after-avatar-click.png",
        PROJECT_DIR / "resource" / "image" / "game" / "profile_opened.png",
        (245, 275, 475, 385),
    ),
    (
        PROJECT_DIR / "debug" / "jiuxiao-current.png",
        PROJECT_DIR / "resource" / "image" / "game" / "chat_back_button.png",
        (15, 1195, 108, 1305),
    ),
)


def find_wechat_window(target_title: str = "微信"):
    candidates = []
    for window in Toolkit.find_desktop_windows():
        title = window.window_name.strip()
        class_name = window.class_name.strip()
        if title == target_title:
            return window
        if "微信" in title or "WeChat" in title or "Weixin" in title:
            candidates.append(window)
        elif class_name.startswith("Qt") and title:
            candidates.append(window)

    details = "\n".join(
        f"- {item.window_name!r} ({item.class_name}, hwnd={item.hwnd})" for item in candidates
    )
    raise RuntimeError(f"没有找到标题为{target_title!r}的窗口。候选窗口：\n{details or '无'}")


def find_exact_window(target_title: str, class_name: str | None = None):
    for window in Toolkit.find_desktop_windows():
        if window.window_name.strip() != target_title:
            continue
        if class_name is None or window.class_name.strip() == class_name:
            return window
    return None


def create_controller(window, foreground: bool = False) -> Win32Controller:
    screencap = (
        MaaWin32ScreencapMethodEnum.Foreground
        if foreground
        else MaaWin32ScreencapMethodEnum.Background
    )
    controller = Win32Controller(
        hWnd=window.hwnd,
        screencap_method=screencap,
        mouse_method=MaaWin32InputMethodEnum.Seize,
        keyboard_method=MaaWin32InputMethodEnum.Seize,
    )
    connection = controller.post_connection().wait()
    if not connection.succeeded:
        raise RuntimeError("连接微信窗口失败")
    return controller


def save_screenshot(controller: Win32Controller, output: Path) -> None:
    from PIL import Image

    image = controller.post_screencap().wait().get()
    if image is None or image.size == 0:
        raise RuntimeError("截图为空")

    output.parent.mkdir(parents=True, exist_ok=True)
    # Maa 图像缓冲使用 OpenCV 的 BGR 通道顺序。
    Image.fromarray(image[:, :, ::-1]).save(output)
    print(f"截图已保存：{output}，尺寸={image.shape[1]}x{image.shape[0]}")


def run_pipeline(controller: Win32Controller, entry: str) -> None:
    resource = Resource()
    resource_job = resource.post_bundle(PROJECT_DIR / "resource").wait()
    if not resource_job.succeeded:
        raise RuntimeError("加载 resource 失败")

    tasker = Tasker()
    tasker.bind(resource, controller)
    if not tasker.inited:
        raise RuntimeError("Tasker 初始化失败")

    task_job = tasker.post_task(entry).wait()
    if not task_job.succeeded:
        raise RuntimeError(f"任务执行失败：{entry}")
    print(f"任务执行成功：{entry}")


def prepare_assets() -> None:
    from PIL import Image

    for source, target, box in ASSET_CROPS:
        if not source.exists():
            raise RuntimeError(f"缺少生成模板所需的诊断截图：{source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            image.crop(box).save(target)
        print(f"模板已生成：{target}")


def run_offline_tests() -> None:
    import numpy as np
    from PIL import Image

    resource = Resource()
    if not resource.post_bundle(PROJECT_DIR / "resource").wait().succeeded:
        raise RuntimeError("Maa 加载 resource 失败")
    print("Maa resource 与 Pipeline 解析通过")

    for source, target, box in ASSET_CROPS:
        with Image.open(source) as screenshot, Image.open(target) as template:
            actual = np.asarray(screenshot.crop(box).convert("RGB"))
            expected = np.asarray(template.convert("RGB"))
        if actual.shape != expected.shape or not np.array_equal(actual, expected):
            raise RuntimeError(f"模板与来源截图不一致：{target}")
        print(f"模板来源校验通过：{target.name}")


def run_workflow() -> None:
    game_window = find_exact_window("九霄仙府", "Chrome_WidgetWin_0")
    if game_window is None:
        panel_window = find_exact_window("微信", "Chrome_WidgetWin_0")
        if panel_window is None:
            main_window = find_exact_window("微信", "Qt51514QWindowIcon")
            if main_window is None:
                raise RuntimeError("没有找到微信主窗口")
            main_controller = create_controller(main_window)
            main_controller.post_screencap().wait()
            if not main_controller.post_click(35, 412).wait().succeeded:
                raise RuntimeError("打开微信小程序面板失败")
            time.sleep(2)
            panel_window = find_exact_window("微信", "Chrome_WidgetWin_0")
        if panel_window is None:
            raise RuntimeError("没有找到微信小程序面板")

        panel_controller = create_controller(panel_window)
        run_pipeline(panel_controller, "打开九霄仙府")
        for _ in range(30):
            time.sleep(1)
            game_window = find_exact_window("九霄仙府", "Chrome_WidgetWin_0")
            if game_window is not None:
                break
        if game_window is None:
            raise RuntimeError("点击入口后没有等到九霄仙府窗口")

    game_controller = create_controller(game_window)
    run_pipeline(game_controller, "打开或确认宗门信息")


def main() -> int:
    parser = argparse.ArgumentParser(description="微信小游戏 MaaFramework 自动化")
    parser.add_argument(
        "command",
        nargs="?",
        default="workflow",
        choices=(
            "windows",
            "screenshot",
            "click",
            "key",
            "input",
            "search-game",
            "prepare-assets",
            "offline-test",
            "workflow",
            "run",
        ),
        help="要执行的操作；不填写时默认执行完整 workflow",
    )
    parser.add_argument("--x", type=int)
    parser.add_argument("--y", type=int)
    parser.add_argument("--key", type=int, default=13, help="Win32 虚拟键码，默认 Enter(13)")
    parser.add_argument("--entry", default="进入九霄仙府并点击头像")
    parser.add_argument("--window-title", default="微信")
    parser.add_argument("--text", default="九霄仙府")
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "debug" / "wechat.png")
    parser.add_argument("--foreground", action="store_true")
    args = parser.parse_args()

    Toolkit.init_option(
        PROJECT_DIR,
        {
            "logging": True,
            "save_draw": False,
            "save_on_error": False,
            "stdout_level": 2,
        },
    )

    if args.command == "windows":
        for window in Toolkit.find_desktop_windows():
            if window.window_name or "Qt" in window.class_name:
                print(window.hwnd, repr(window.window_name), repr(window.class_name))
        return 0

    if args.command == "prepare-assets":
        prepare_assets()
        return 0

    if args.command == "offline-test":
        run_offline_tests()
        return 0

    if args.command == "workflow":
        run_workflow()
        return 0

    window = find_wechat_window(args.window_title)
    print(f"使用窗口：{window.window_name!r}，{window.class_name}，hwnd={window.hwnd}")
    controller = create_controller(window, args.foreground)

    if args.command == "screenshot":
        save_screenshot(controller, args.output)
    elif args.command == "click":
        if args.x is None or args.y is None:
            parser.error("click 必须提供 --x 和 --y")
        click = controller.post_click(args.x, args.y).wait()
        if not click.succeeded:
            raise RuntimeError(f"点击失败：({args.x}, {args.y})")
        print(f"点击成功：({args.x}, {args.y})")
    elif args.command == "input":
        input_job = controller.post_input_text(args.text).wait()
        if not input_job.succeeded:
            raise RuntimeError(f"输入失败：{args.text!r}")
        print(f"输入成功：{args.text!r}")
    elif args.command == "key":
        key_job = controller.post_click_key(args.key).wait()
        if not key_job.succeeded:
            raise RuntimeError(f"按键失败：{args.key}")
        time.sleep(2)
        save_screenshot(controller, args.output)
    elif args.command == "search-game":
        # 默认截图规范化为短边 720，搜索框位于微信客户区左上方。
        click = controller.post_click(180, 65).wait()
        if not click.succeeded:
            raise RuntimeError("点击微信搜索框失败")
        time.sleep(0.5)
        input_job = controller.post_input_text(args.text).wait()
        if not input_job.succeeded:
            raise RuntimeError(f"输入搜索词失败：{args.text!r}")
        time.sleep(2)
        save_screenshot(controller, args.output)
    else:
        run_pipeline(controller, args.entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
