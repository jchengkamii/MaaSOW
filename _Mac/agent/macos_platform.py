"""Native macOS window discovery and permission checks (MaaFramework 5.12.3)."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from maa.controller import MacOSController
from maa.define import MaaMacOSInputMethodEnum, MaaMacOSScreencapMethodEnum, MaaMacOSPermissionEnum
from maa.toolkit import Toolkit

ROOT = Path(__file__).resolve().parents[1]

def settings():
    path = ROOT / "config" / "macos.json"
    values = {"window_title_regex": "^九霄仙府$", "input_method": "PostToPid"}
    if path.exists():
        values.update(json.loads(path.read_text(encoding="utf-8")))
    re.compile(values["window_title_regex"])
    if values["input_method"] != "PostToPid":
        raise ValueError("此版本仅允许 PostToPid 后台输入，不会回退到全局鼠标事件。")
    return values

def require_permissions(request=False):
    if sys.platform != "darwin":
        raise RuntimeError("此版本需要 macOS 14 或以上；不能在 Windows 上控制游戏。")
    missing = []
    for permission, label in ((MaaMacOSPermissionEnum.ScreenCapture, "屏幕录制"),
                              (MaaMacOSPermissionEnum.Accessibility, "辅助功能")):
        if not Toolkit.macos_check_permission(permission):
            if request:
                Toolkit.macos_request_permission(permission)
            missing.append(label)
    if missing:
        raise RuntimeError("请在系统设置 → 隐私与安全性中授权启动本程序的终端/Python："
                           + "、".join(missing) + "。授权后退出并重新启动。")

def find_game_window():
    require_permissions()
    pattern = settings()["window_title_regex"]
    windows = [w for w in Toolkit.find_desktop_windows() if re.search(pattern, w.window_name)]
    if len(windows) > 1:
        raise RuntimeError("找到多个匹配的游戏窗口，请关闭多余窗口或修改 config/macos.json 的标题表达式。")
    return windows[0] if windows else None

def connect_window(window):
    settings()  # Reject global input even when an old configuration was copied here.
    require_permissions()
    controller = MacOSController(
        window_id=window.hwnd,
        screencap_method=MaaMacOSScreencapMethodEnum.ScreenCaptureKit,
        input_method=MaaMacOSInputMethodEnum.PostToPid,
    )
    if not controller.set_screenshot_target_short_side(720):
        raise RuntimeError("设置截图短边 720 失败")
    if not controller.post_connection().wait().succeeded:
        raise RuntimeError("连接游戏失败，请检查系统权限并保持游戏窗口可见。")
    return controller
