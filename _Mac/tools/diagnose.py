"""Read-only Mac permission/window/screenshot diagnosis; never clicks."""
from pathlib import Path
import struct
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

def main():
    from agent.macos_platform import require_permissions, find_game_window, connect_window
    from maa.toolkit import Toolkit
    from agent.core import AutomationEngine
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
    engine = AutomationEngine(log=lambda text: print(text, flush=True))
    engine.reload_resources()
    print("权限、连接、截图和资源加载检查通过；本检查没有点击游戏。", flush=True)
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"检查失败：{exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
