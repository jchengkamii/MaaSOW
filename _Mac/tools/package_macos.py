"""Create the Mac full bundle or a root-level script update ZIP."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_distribution import build_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version")
    parser.add_argument("--scripts-only", action="store_true")
    args = parser.parse_args()
    version = args.version or json.loads((ROOT / "interface.json").read_text(encoding="utf-8"))["version"]
    archive = build_package(ROOT, ROOT / "dist", version, scripts_only=args.scripts_only)
    if not args.scripts_only:
        alias = ROOT / "dist/MaaSOW-macOS.zip"
        shutil.copy2(archive, alias)
        with alias.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        alias.with_suffix(".zip.sha256").write_text(digest + "  " + alias.name + "\n", encoding="ascii")
    print(archive, flush=True)


if __name__ == "__main__":
    main()
