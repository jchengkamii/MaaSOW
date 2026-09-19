"""Build an allowlisted distribution with online environment setup."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
ROOT = Path(__file__).resolve().parents[1]

def main() -> None:
    subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "generate_interface.py")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT, check=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stage = ROOT / "build" / stamp / "release-1.0.0"
    stage.mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.log")
    for folder in ("agent", "resource", "maafw", "licenses"):
        shutil.copytree(ROOT / folder, stage / folder, ignore=ignore)
    for name in ("interface.json", "generate_interface.py", "requirements.txt",
                 "九霄仙府自动化测试.exe", "使用前环境准备.bat"):
        shutil.copy2(ROOT / name, stage / name)
    (stage / "tools").mkdir()
    for name in ("prepare_environment.ps1", "check_environment.py"):
        shutil.copy2(ROOT / "tools" / name, stage / "tools" / name)
    shutil.copy2(ROOT / "tools/DISTRIBUTION_README.md", stage / "使用说明.md")
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    archive = out / "release-1.0.0.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(stage.parent).as_posix())
    staging_parent = stage.parent.resolve()
    if not staging_parent.is_relative_to((ROOT / "build").resolve()):
        raise RuntimeError("Unexpected staging path")
    shutil.rmtree(staging_parent)
    print(archive, flush=True)

if __name__ == "__main__":
    main()
