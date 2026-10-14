"""Check the distribution without operating the game."""
from __future__ import annotations
import ctypes
import importlib
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
    for requirement in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        requirement = requirement.partition("#")[0].strip()
        if requirement:
            name, expected = requirement.split("==")
            assert metadata.version(name).removeprefix("v") == expected, f"{name} requires {expected}"
    import maa
    import numpy
    import strenum
    import PIL
    from PIL import Image
    from maa.controller import Win32Controller
    for module in (maa, numpy, strenum, PIL):
        assert Path(module.__file__).resolve().is_relative_to(ROOT / ".runtime"), module.__file__
    # Exercise the delayed dependency used to save failed dispatch frames.
    from io import BytesIO
    image = Image.fromarray(numpy.zeros((2, 2, 3), dtype=numpy.uint8))
    image.save(BytesIO(), format="PNG")
    if "--imports-only" in sys.argv:
        return
    from agent.core import CaseLoader
    from agent.recognition_fallback import apply_full_image_fallbacks
    from maa.resource import Resource
    from maa.toolkit import Toolkit
    from maa.library import Library
    expected_framework = metadata.version("MaaFw").removeprefix("v")
    assert Library.version().removeprefix("v") == expected_framework, "Python framework DLL version mismatch"
    with __import__("os").add_dll_directory(str(ROOT / "maafw")):
        for name in ("MaaFramework.dll", "MaaToolkit.dll", "MaaWin32ControlUnit.dll",
                     "MaaAgentClient.dll", "MaaAgentServer.dll"):
            ctypes.WinDLL(str(ROOT / "maafw" / name))
        frontend_framework = ctypes.WinDLL(str(ROOT / "maafw/MaaFramework.dll"))
        frontend_framework.MaaVersion.restype = ctypes.c_char_p
        frontend_framework.MaaVersion.argtypes = []
        assert frontend_framework.MaaVersion().decode().removeprefix("v") == expected_framework, "Frontend framework DLL version mismatch"
    Toolkit.init_option(ROOT, {"logging": False, "save_draw": False, "save_on_error": False})
    resource = Resource()
    assert resource.post_bundle(ROOT / "resource/base").wait().succeeded, "Resource loading failed"
    apply_full_image_fallbacks(resource)
    cases = CaseLoader().load()
    for case in cases:
        if case.handler == "python":
            module, name = case.extension.split(":")
            assert callable(getattr(importlib.import_module(module), name)), case.extension
    proc = subprocess.run([sys.executable, "-X", "utf8", "-m", "agent.worker", "--help"],
                          cwd=ROOT, capture_output=True, encoding="utf-8", timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # Without a socket the Agent should register its actions and print usage, then exit.
    # This exercises MaaAgentBinary and the Agent DLL without connecting to the game.
    proc = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "agent/main.py")],
                          cwd=ROOT, capture_output=True, encoding="utf-8", timeout=30)
    assert proc.returncode == 2 and "Usage: agent/main.py" in proc.stdout, proc.stdout + proc.stderr
    print(f"Environment OK: Python {sys.version.split()[0]}, {len(cases)} tasks, native resources, worker and Agent OK.")

if __name__ == "__main__":
    try:
        main()
    except (ImportError, OSError, RuntimeError, AssertionError, subprocess.TimeoutExpired) as exc:
        print(f"[MaaSOW] Environment check failed: {exc}")
        print("[MaaSOW] Run 使用前环境准备.bat; pip alone does not prepare the MXU runtime.")
        raise SystemExit(1)
