"""Build Mac full bundles and MXU-compatible Mac-only script updates."""
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def resolve_version(explicit: str | None = None) -> str:
    if explicit is not None:
        return explicit.removeprefix("v")
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "origin", "refs/tags/v*"],
        cwd=ROOT, check=True, capture_output=True, text=True, timeout=30,
    )
    versions = [
        match.group(1)
        for line in result.stdout.splitlines()
        if (match := re.search(r"\srefs/tags/v((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))$", line))
    ]
    if not versions:
        raise RuntimeError("No stable Git release tag found; pass --version explicitly")
    return max(versions, key=lambda value: tuple(map(int, value.split("."))))



def build_package(root: Path, output: Path, version: str, *, scripts_only: bool = False) -> Path:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise ValueError("version must be a stable major.minor.patch version")
    output.mkdir(parents=True, exist_ok=True)
    kind = "scripts" if scripts_only else "full"
    archive = output / f"MaaSOW-{kind}-macos-universal-v{version}.zip"
    prefix = "" if scripts_only else "MaaSOW-macOS/"
    folders = ("agent", "resource", "tools") if scripts_only else ("agent", "resource", "tools", "licenses", "tests")
    files = [root / name for name in ("README.md", "interface.json", "generate_interface.py", "requirements.txt", "launcher.py")]
    for name in ("AGENTS.md", "source_snapshot.json", "同步记录.md", "验证记录.md"):
        if (root / name).is_file():
            files.append(root / name)
    files.extend(root.glob("*.command"))
    if not scripts_only:
        manifest = json.loads((root / "vendor/manifest.json").read_text(encoding="utf-8"))
        files.append(root / "vendor/manifest.json")
        for asset in manifest["assets"]:
            path = root / "vendor" / asset["name"]
            if not path.resolve().is_relative_to((root / "vendor").resolve()):
                raise ValueError("Invalid runtime archive path")
            with path.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != asset["sha256"]:
                    raise ValueError(f"Runtime archive checksum mismatch: {path.name}")
            files.append(path)
        files.extend(root / "config" / name for name in ("macos.json", "maa_option.json"))
    for folder in folders:
        files.extend(path for path in (root / folder).rglob("*") if path.is_file())
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(set(files)):
            relative = path.relative_to(root)
            if any(part in ("__pycache__", "node_modules", ".git") for part in relative.parts) or path.suffix in (".pyc", ".pyo", ".log"):
                continue
            if path.suffix.lower() in (".exe", ".dll", ".pyd", ".bat", ".ps1"):
                raise ValueError(f"Windows-only file cannot be distributed for Mac: {relative}")
            data = path.read_bytes()
            if relative.as_posix() == "interface.json":
                interface = json.loads(data.decode("utf-8-sig"))
                controllers = interface.get("controller", [])
                if not controllers or any(c.get("type") != "MacOS" or c.get("macos", {}).get("input") != "PostToPid" for c in controllers):
                    raise ValueError("Mac bundle requires PostToPid controllers")
                if interface.get("agent", {}).get("child_exec") != "./.venv/bin/python3":
                    raise ValueError("Mac bundle requires the Mac Python Agent path")
                interface["version"] = version
                data = (json.dumps(interface, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            info = zipfile.ZipInfo(prefix + relative.as_posix())
            info.create_system = 3
            info.external_attr = (0o100755 if path.suffix == ".command" else 0o100644) << 16
            bundle.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError("ZIP verification failed")
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n", encoding="ascii")
    return archive
