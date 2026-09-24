from pathlib import Path
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from tools import install_mxu as installer

class MxuInstallTests(unittest.TestCase):
    def test_architecture_selection_and_rejection(self):
        self.assertEqual("aarch64", installer.architecture("arm64"))
        self.assertEqual("aarch64", installer.architecture("aarch64"))
        self.assertEqual("x86_64", installer.architecture("x86_64"))
        with self.assertRaises(RuntimeError):
            installer.architecture("mips")

    def test_archive_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("../outside", "/outside", "C:/outside", "a/../../outside", "..\\outside"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    installer.safe_target(Path(directory), name)

    def test_both_official_archives_install_and_verify(self):
        # Real pinned official files are unpacked, never executed on the build host.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(installer.ROOT / "vendor", root / "vendor")
            for arch in ("aarch64", "x86_64"):
                with self.subTest(architecture=arch):
                    installer.install(root, arch)
                    installer.verify_macho(root / "mxu", arch)
                    with patch.object(installer, "architecture", return_value=arch):
                        installer.verify_installed(root)
                    for name in installer.REQUIRED_LIBS:
                        installer.verify_macho(root / "maafw" / name, arch)
                    self.assertTrue((root / "licenses/MXU-LICENSE").is_file())
                    self.assertTrue((root / "licenses/MaaFramework-LICENSE.md").is_file())
            (root / "mxu").write_bytes(b"bad")
            with patch.object(installer, "architecture", return_value="x86_64"), self.assertRaisesRegex(RuntimeError, "运行文件"):
                installer.verify_installed(root)

    def test_checksum_failure_blocks_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "vendor").mkdir()
            manifest = json.loads((installer.ROOT / "vendor/manifest.json").read_text(encoding="utf-8"))
            (root / "vendor/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            for asset in manifest["assets"]:
                (root / "vendor" / asset["name"]).write_bytes(b"bad")
            with self.assertRaisesRegex(RuntimeError, "校验失败"):
                installer.install(root, "aarch64")
            self.assertFalse((root / "mxu").exists())

if __name__ == "__main__":
    unittest.main()
