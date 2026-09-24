"""Build the synchronized MaaSOW MXU customization on macOS."""
from pathlib import Path
import shutil
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.prepare_mxu import prepare, MXU_REVISION
from tools.install_mxu import verify_installed, install_custom_binary


def build():
    if sys.platform != "darwin":
        raise RuntimeError("定制 MXU 的 Mac 二进制必须在 Mac 上构建。")
    for command in ("git", "node", "pnpm", "cargo", "xcrun"):
        if not shutil.which(command):
            raise RuntimeError(f"缺少 {command}；请按 tools/AUTO_UPDATE.md 安装构建依赖。")
    if int(subprocess.check_output(["node", "--version"], text=True).lstrip("v").split(".")[0]) < 22:
        raise RuntimeError("需要 Node.js 22 或以上")
    if subprocess.check_output(["pnpm", "--version"], text=True).strip() != "10.28.0":
        raise RuntimeError("需要 pnpm 10.28.0")
    subprocess.run(["xcrun", "--find", "clang"], check=True)
    verify_installed(ROOT)
    source = ROOT / "build/mxu-custom-v2.4.5"
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", "--branch", "v2.4.5", "https://github.com/MistEO/MXU.git", str(source)], check=True)
    prepare(source)  # Checks the pinned source commit before applying the Mac updater.
    subprocess.run(["pnpm", "install", "--frozen-lockfile"], cwd=source, check=True)
    subprocess.run(["node", "--experimental-strip-types", "--test", "src/services/mainRelease.test.mjs"], cwd=source, check=True)
    subprocess.run(["pnpm", "tauri", "build", "--no-bundle"], cwd=source, check=True)
    binary = source / "src-tauri/target/release/mxu"
    install_custom_binary(binary, ROOT)
    print(f"定制 MXU 已安装（源码 {MXU_REVISION}）。重新运行启动脚本后，可在设置中使用脚本自动更新。")


if __name__ == "__main__":
    try:
        build()
    except Exception as exc:
        raise SystemExit(str(exc))
