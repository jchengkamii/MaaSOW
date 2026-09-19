"""Check the distribution without operating the game."""
from __future__ import annotations
import ctypes
import importlib.metadata as metadata
from pathlib import Path
import struct
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main() -> None:
    assert sys.version_info[:2] == (3, 12), "Python 3.12 required"
    assert struct.calcsize("P") == 8, "x64 Python required"
    import maa
    import numpy
    import strenum
    from maa.controller import Win32Controller
    for requirement in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if requirement.strip() and not requirement.startswith("#"):
            name, expected = requirement.strip().split("==")
            assert metadata.version(name) == expected, f"{name} requires {expected}"
    for module in (maa, numpy, strenum):
        assert Path(module.__file__).resolve().is_relative_to(ROOT / ".runtime"), module.__file__
    if "--imports-only" in sys.argv:
        return
    from agent.core import CaseLoader
    from maa.resource import Resource
    from maa.toolkit import Toolkit
    with __import__("os").add_dll_directory(str(ROOT / "maafw")):
        ctypes.WinDLL(str(ROOT / "maafw/MaaFramework.dll"))
    Toolkit.init_option(ROOT, {"logging": False, "save_draw": False, "save_on_error": False})
    resource = Resource()
    assert resource.post_bundle(ROOT / "resource/base").wait().succeeded, "Resource loading failed"
    cases = CaseLoader().load()
    proc = subprocess.run([sys.executable, "-X", "utf8", "-m", "agent.worker", "--help"],
                          cwd=ROOT, capture_output=True, encoding="utf-8", timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    print(f"Environment OK: Python {sys.version.split()[0]}, {len(cases)} tasks, native resources and worker OK.")

if __name__ == "__main__":
    try:
        main()
    except (ImportError, AssertionError) as exc:
        if "--imports-only" not in sys.argv:
            raise
        print(f"[MaaSOW] Python dependencies need preparation: {exc}")
        raise SystemExit(1)
