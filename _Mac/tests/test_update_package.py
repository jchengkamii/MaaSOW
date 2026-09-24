import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from tools.build_distribution import build_package


class UpdatePackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        for name in ("agent/main.py", "agent/__pycache__/main.pyc", "resource/interface.tasks.json",
                     "resource/base/pipeline/test.json", "resource/tasks/task.json", "vendor/manifest.json",
                     "licenses/MXU-LICENSE.txt", "tools/install_mxu.py", "tools/prepare_mxu.py",
                     "tools/mxu/mainUpdate.ts", "tests/test_macos.py", "config/macos.json", "config/maa_option.json",
                     "config/mxu-MaaSOW.json", "config/mxu-runtime.json", ".venv/bin/python3", "debug/private.log",
                     "README.md", "launcher.py", "generate_interface.py", "requirements.txt", "使用前环境准备.command"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")
        self.interface = {"version": "1.0.1", "name": "MaaSOW",
                          "controller": [{"type": "MacOS", "macos": {"input": "PostToPid"}}],
                          "agent": {"child_exec": "./.venv/bin/python3"}}
        (self.root / "interface.json").write_text(json.dumps(self.interface), encoding="utf-8")
        self.output = Path(self.temporary.name) / "dist"

    def test_scripts_archive_is_rooted_for_mxu_and_preserves_machine_state(self):
        archive = build_package(self.root, self.output, "1.1.9", scripts_only=True)
        self.assertEqual("MaaSOW-scripts-macos-universal-v1.1.9.zip", archive.name)
        with zipfile.ZipFile(archive) as package:
            names = set(package.namelist())
            self.assertIn("agent/main.py", names)
            self.assertIn("resource/interface.tasks.json", names)
            self.assertIn("launcher.py", names)
            self.assertIn("tools/install_mxu.py", names)
            self.assertEqual("1.1.9", json.loads(package.read("interface.json"))["version"])
            self.assertFalse(any(n.startswith(("config/", ".venv/", "debug/", "maafw/", "vendor/", "licenses/", "tests/")) for n in names))
            self.assertNotIn("agent/__pycache__/main.pyc", names)
            self.assertTrue(package.getinfo("使用前环境准备.command").external_attr >> 16 & 0o111)
        self.assertEqual("1.0.1", json.loads((self.root / "interface.json").read_text())["version"])

    def test_full_bundle_has_runtime_sources_and_only_default_configs(self):
        archive = build_package(self.root, self.output, "1.1.9")
        with zipfile.ZipFile(archive) as package:
            names = set(package.namelist())
            for name in ("vendor/manifest.json", "tools/prepare_mxu.py", "tools/mxu/mainUpdate.ts", "interface.json", "config/macos.json"):
                self.assertIn("MaaSOW-macOS/" + name, names)
            self.assertNotIn("MaaSOW-macOS/config/mxu-runtime.json", names)
            self.assertNotIn("MaaSOW-macOS/config/mxu-MaaSOW.json", names)

    def test_invalid_version_cannot_form_output_path(self):
        for version in ("../oops", "1.2", "v1.2.3", "1.2.3-dev", "01.2.3"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                build_package(self.root, self.output, version)

    def test_windows_interface_and_global_input_are_rejected(self):
        for controller in ({"type": "Win32"}, {"type": "MacOS", "macos": {"input": "GlobalEvent"}}):
            self.interface["controller"] = [controller]
            (self.root / "interface.json").write_text(json.dumps(self.interface), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "PostToPid"):
                build_package(self.root, self.output, "1.1.9", scripts_only=True)


if __name__ == "__main__":
    unittest.main()
