"""Start the native MXU frontend; no Tk or foreground mouse fallback."""
from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def validate_background_config(root=ROOT):
    root = Path(root)
    interface = json.loads((root / "interface.json").read_text(encoding="utf-8"))
    controllers = interface.get("controller", [])
    if not controllers or any(c.get("type") != "MacOS" or c.get("macos", {}).get("input") != "PostToPid" for c in controllers):
        raise RuntimeError("MXU 控制器必须使用 MacOS / PostToPid 后台输入。")
    path = root / "config/macos.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("input_method", "PostToPid") != "PostToPid":
        raise RuntimeError("任务控制器只允许 PostToPid；请重新运行环境准备或恢复后台输入配置。")


def run_mxu(root=ROOT):
    root = Path(root)
    from tools.install_mxu import verify_installed
    validate_background_config(root)
    verify_installed(root)
    # Run from the bundle root so MXU finds interface.json, maafw/ and the Agent.
    process = subprocess.Popen([str(root / "mxu")], cwd=root,
                               env={**os.environ, "PYTHONUTF8": "1"})
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        return 130
    finally:
        from agent.custom.action.stop_auto_help.stop_auto_help import run
        print(run(None, None), flush=True)


def main():
    if sys.platform != "darwin" or int(platform.mac_ver()[0].split(".")[0]) < 14:
        raise RuntimeError("此版本需要 macOS 14 或以上。")
    return run_mxu()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"启动/退出 MXU 失败：{exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
