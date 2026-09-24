"""Build a distribution or an MXU-compatible scripts update (ZIP root = install root)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build_package(root: Path, output: Path, version: str, *, scripts_only: bool = False) -> Path:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise ValueError("version must be a stable major.minor.patch version")
    output.mkdir(parents=True, exist_ok=True)
    kind = "scripts" if scripts_only else "full"
    archive = output / f"MaaSOW-{kind}-win-x86_64-v{version}.zip"
    # TemporaryDirectory only removes the staging directory it created.
    with tempfile.TemporaryDirectory(prefix="maasow-package-") as temporary:
        stage = Path(temporary)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.log")
        folders = ("agent", "resource") if scripts_only else ("agent", "resource", "maafw", "licenses")
        for folder in folders:
            shutil.copytree(root / folder, stage / folder, ignore=ignore)
        for name in ("generate_interface.py", "requirements.txt", "使用前环境准备.bat"):
            shutil.copy2(root / name, stage / name)
        if not scripts_only:
            shutil.copy2(root / "九霄小助手.exe", stage / "九霄小助手.exe")
            # Ship the customization and reproducible build instructions with the AGPL frontend.
            source_tools = stage / "mxu-source" / "tools"
            source_tools.mkdir(parents=True)
            shutil.copytree(root / "tools/mxu", source_tools / "mxu", ignore=ignore)
            for name in ("prepare_mxu.py", "AUTO_UPDATE.md"):
                shutil.copy2(root / "tools" / name, source_tools / name)
        interface = json.loads((root / "interface.json").read_text(encoding="utf-8-sig"))
        interface["version"] = version
        (stage / "interface.json").write_text(json.dumps(interface, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (stage / "tools").mkdir()
        for name in ("prepare_environment.ps1", "check_environment.py"):
            shutil.copy2(root / "tools" / name, stage / "tools" / name)
        shutil.copy2(root / "tools/DISTRIBUTION_README.md", stage / "使用说明.md")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as package:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    package.write(path, path.relative_to(stage).as_posix())
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=None)
    parser.add_argument("--scripts-only", action="store_true")
    args = parser.parse_args()
    version = args.version or json.loads((ROOT / "interface.json").read_text(encoding="utf-8-sig"))["version"]
    subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "generate_interface.py")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT, check=True)
    print(build_package(ROOT, ROOT / "dist", version, scripts_only=args.scripts_only), flush=True)


if __name__ == "__main__":
    main()
