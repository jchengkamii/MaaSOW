"""Read-only Mac permission/window/screenshot diagnosis; never clicks."""
from pathlib import Path
import struct
import argparse
import importlib
import importlib.metadata as metadata
import ctypes
import subprocess
import sys
import zlib
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def save_png(path, image):
    rgb = image[:, :, :3][:, :, ::-1].copy()
    height, width = rgb.shape[:2]
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    raw = b"".join(b"\0" + row.tobytes() for row in rgb)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

def check_environment(imports_only=False):
    """Verify local dependencies and delayed Pillow usage without game input."""
    if sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
        raise RuntimeError("需要 64 位 Python 3.12")
    environment = (ROOT / ".venv").resolve()
    if Path(sys.prefix).resolve() != environment:
        raise RuntimeError("请使用本目录 .venv/bin/python3，重新运行环境准备脚本。")
    for requirement in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        requirement = requirement.partition("#")[0].strip()
        if requirement:
            name, expected = requirement.split("==")
            if metadata.version(name) != expected:
                raise RuntimeError(f"{name} 需要版本 {expected}")
    for name in ("maa", "numpy", "strenum", "PIL", "psutil"):
        module = importlib.import_module(name)
        if not Path(module.__file__).resolve().is_relative_to(environment):
            raise RuntimeError(f"{name} 未安装在本项目环境中：{module.__file__}")
    import numpy
    from io import BytesIO
    from PIL import Image
    from maa.controller import MacOSController
    Image.fromarray(numpy.zeros((2, 2, 3), dtype=numpy.uint8)).save(BytesIO(), format="PNG")
    if imports_only:
        return
    if sys.platform != "darwin":
        raise RuntimeError("原生运行库检查需要在 Mac 上运行。")
    from tools.install_mxu import verify_installed, REQUIRED_LIBS
    from launcher import validate_background_config
    verify_installed()
    validate_background_config()
    for name in REQUIRED_LIBS:
        ctypes.CDLL(str(ROOT / "maafw" / name))
    from agent.core import CaseLoader, AutomationEngine
    engine = AutomationEngine(log=lambda text: print(text, flush=True))
    engine.reload_resources()
    cases = CaseLoader().load()
    for case in cases:
        if case.handler == "python":
            module, name = case.extension.split(":")
            if not callable(getattr(importlib.import_module(module), name)):
                raise RuntimeError(f"任务入口不可调用：{case.extension}")
    probes = [(["-m", "agent.worker", "--help"], 0, None),
              ([str(ROOT / "agent/main.py")], 2, "Usage: agent/main.py")]
    for arguments, expected, marker in probes:
        result = subprocess.run([sys.executable, "-X", "utf8", *arguments], cwd=ROOT,
                                capture_output=True, encoding="utf-8", timeout=30)
        if result.returncode != expected or (marker and marker not in result.stdout):
            raise RuntimeError(result.stdout + result.stderr)
    print(f"Environment OK: {len(cases)} tasks, dependencies, native libraries, worker and Agent.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imports-only", action="store_true")
    parser.add_argument("--environment-only", action="store_true")
    args = parser.parse_args()
    check_environment(imports_only=args.imports_only)
    if args.imports_only or args.environment_only:
        return 0
    from agent.macos_platform import require_permissions, find_game_window, connect_window
    from maa.toolkit import Toolkit
    from launcher import validate_background_config
    validate_background_config()
    require_permissions(request=True)
    print("输入方式：PostToPid（后台定向投递，不使用全局鼠标事件）", flush=True)
    print("当前窗口：", flush=True)
    for window in Toolkit.find_desktop_windows():
        print(f"  {window.hwnd}: {window.window_name}", flush=True)
    window = find_game_window()
    if window is None:
        raise RuntimeError("没有找到游戏。请打开九霄仙府；标题不同时修改 config/macos.json。")
    controller = connect_window(window)
    if not controller.post_screencap().wait().succeeded:
        raise RuntimeError("截图失败，请检查屏幕录制权限。")
    image = controller.cached_image
    if image is None or image.size == 0:
        raise RuntimeError("截图为空")
    path = ROOT / "debug" / "macos_screenshot.png"
    save_png(path, image)
    print(f"截图已保存：{path}，尺寸 {image.shape[1]} × {image.shape[0]}", flush=True)
    print("权限、连接、截图和资源加载检查通过；本检查没有点击游戏。", flush=True)
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"检查失败：{exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
