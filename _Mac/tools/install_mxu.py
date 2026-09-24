"""Install pinned, checksum-verified Mac MXU and MaaFramework from vendor/."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import struct
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CUSTOM_MXU_REVISION = "115fcb39d75718f8bd53e76511322660b8af00ec"
CUSTOM_MXU_VERSION = "2.4.5"
REQUIRED_LIBS = ("libMaaFramework.dylib", "libMaaToolkit.dylib", "libMaaAgentClient.dylib", "libMaaAgentServer.dylib", "libMaaMacOSControlUnit.dylib")


def architecture(machine=None):
    value = (machine or platform.machine()).lower()
    if value in ("arm64", "aarch64"):
        return "aarch64"
    if value in ("x86_64", "amd64"):
        return "x86_64"
    raise RuntimeError(f"不支持的 Mac 架构：{value}")


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def verify_macho(path, arch):
    with path.open("rb") as source:
        header = source.read(8)
    expected = {"aarch64": 0x0100000c, "x86_64": 0x01000007}[arch]
    if len(header) != 8 or header[:4] != b"\xcf\xfa\xed\xfe" or struct.unpack("<I", header[4:])[0] != expected:
        raise RuntimeError(f"不是预期架构的 Mac 可执行文件：{path.name} ({arch})")


def safe_target(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise ValueError(f"非法归档路径：{name}")
    target = root.joinpath(*relative.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"归档路径越界：{name}")
    return target


def install(root=ROOT, arch=None):
    root = Path(root).resolve()
    arch = arch or architecture()
    manifest = json.loads((root / "vendor/manifest.json").read_text(encoding="utf-8"))
    assets = [a for a in manifest["assets"] if f"-macos-{arch}-" in a["name"]]
    if len(assets) != 2:
        raise RuntimeError(f"缺少 {arch} 的 MXU/框架安装包")
    for asset in assets:
        path = safe_target(root / "vendor", asset["name"])
        if not path.is_file() or sha256(path) != asset["sha256"]:
            raise RuntimeError(f"安装包缺失或校验失败：{path.name}，请重新解压完整发行包。")
    # Temporary staging remains inside the selected project and never contains user data.
    with tempfile.TemporaryDirectory(prefix=".mxu-install-", dir=root) as temporary:
        stage = Path(temporary)
        (stage / "licenses").mkdir()
        for asset in assets:
            path = root / "vendor" / asset["name"]
            if path.name.startswith("MXU-"):
                with tarfile.open(path, "r:gz") as bundle:
                    for member in bundle.getmembers():
                        name = PurePosixPath(member.name).as_posix()
                        if name not in ("mxu", "LICENSE", "README.md"):
                            continue
                        if not member.isfile():
                            raise ValueError(f"不支持的 MXU 文件类型：{member.name}")
                        target = stage / "mxu" if name == "mxu" else stage / "licenses" / ("MXU-" + name)
                        with bundle.extractfile(member) as source:
                            target.write_bytes(source.read())
            else:
                with zipfile.ZipFile(path) as bundle:
                    for member in bundle.infolist():
                        if member.filename == "LICENSE.md":
                            (stage / "licenses/MaaFramework-LICENSE.md").write_bytes(bundle.read(member))
                        if not member.filename.startswith("bin/") or member.is_dir():
                            continue
                        if (member.external_attr >> 16) & 0o170000 == 0o120000:
                            raise ValueError("不支持的框架归档符号链接")
                        target = safe_target(stage / "maafw", member.filename[4:])
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(bundle.read(member))
        verify_macho(stage / "mxu", arch)
        for name in REQUIRED_LIBS:
            verify_macho(stage / "maafw" / name, arch)
        files = [p for p in stage.rglob("*") if p.is_file()]
        checksums = {}
        for path in files:
            relative = path.relative_to(stage)
            target = safe_target(root, relative.as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if relative.as_posix() == "mxu" or relative.parts[0] == "maafw":
                target.chmod(0o755)
                checksums[relative.as_posix()] = sha256(target)
        state = {"architecture": arch, "mxu_version": manifest["mxu_version"], "maafw_version": manifest["maafw_version"], "sha256": checksums}
        marker = root / "config/mxu-runtime.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"MXU {manifest['mxu_version']} / MaaFramework {manifest['maafw_version']} ({arch}) 安装完成。")


def verify_installed(root=ROOT):
    root = Path(root)
    marker = root / "config/mxu-runtime.json"
    if not marker.is_file():
        raise RuntimeError("尚未安装 MXU，请先运行 使用前环境准备.command。")
    state = json.loads(marker.read_text(encoding="utf-8"))
    manifest = json.loads((root / "vendor/manifest.json").read_text(encoding="utf-8"))
    custom = state.get("custom_mxu_revision") == CUSTOM_MXU_REVISION and state.get("mxu_version") == CUSTOM_MXU_VERSION
    mxu_matches = custom or (not state.get("custom_mxu_revision") and state.get("mxu_version") == manifest["mxu_version"])
    if state.get("architecture") != architecture() or not mxu_matches or state.get("maafw_version") != manifest["maafw_version"]:
        raise RuntimeError("MXU 版本或 Python 架构不匹配，请重新运行环境准备脚本。")
    for name in ("mxu", *("maafw/" + n for n in REQUIRED_LIBS)):
        path = root / name
        if not path.is_file() or sha256(path) != state.get("sha256", {}).get(name):
            raise RuntimeError(f"运行文件缺失或已改变：{name}，请重新运行环境准备脚本。")


def install_custom_binary(binary, root=ROOT):
    root = Path(root).resolve()
    binary = Path(binary).resolve()
    verify_macho(binary, architecture())
    verify_installed(root)
    target = root / "mxu"
    shutil.copy2(binary, target)
    target.chmod(0o755)
    marker = root / "config/mxu-runtime.json"
    state = json.loads(marker.read_text(encoding="utf-8"))
    state["mxu_version"] = CUSTOM_MXU_VERSION
    state["custom_mxu_revision"] = CUSTOM_MXU_REVISION
    state["sha256"]["mxu"] = sha256(target)
    marker.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if sys.platform != "darwin":
        raise SystemExit("请在 Mac 上运行此安装工具。")
    install()
