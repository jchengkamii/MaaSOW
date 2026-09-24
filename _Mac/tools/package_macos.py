"""Package only portable files and preserve executable bits in the ZIP."""
from pathlib import Path
import hashlib
import zipfile
ROOT = Path(__file__).resolve().parents[1]

def main():
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archive = output / "MaaSOW-macOS.zip"
    folders = ("agent", "resource", "licenses", "tools", "tests", "vendor")
    files = [ROOT / name for name in ("README.md", "验证记录.md", "AGENTS.md", "interface.json", "generate_interface.py", "requirements.txt", "launcher.py")]
    files.extend(ROOT.glob("*.command"))
    files.extend(ROOT / "config" / name for name in ("macos.json", "maa_option.json"))
    for name in folders:
        files.extend(path for path in (ROOT/name).rglob("*") if path.is_file())
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(set(files)):
            if "__pycache__" in path.parts or path.suffix in (".pyc", ".log"):
                continue
            if path.suffix.lower() in (".exe", ".dll", ".pyd", ".bat"):
                raise RuntimeError(f"Windows binary must not be packaged: {path}")
            info = zipfile.ZipInfo("MaaSOW-macOS/" + path.relative_to(ROOT).as_posix())
            info.create_system = 3
            info.external_attr = (0o100755 if path.suffix == ".command" else 0o100644) << 16
            bundle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError("ZIP verification failed")
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n", encoding="ascii")
    print(archive)
    print("SHA256:", digest)

if __name__ == "__main__":
    main()
