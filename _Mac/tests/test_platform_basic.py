"""Mac 平台基础检查。"""
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from agent import macos_platform as mac
from tools import install_mxu as installer


class MacBasicTests(unittest.TestCase):
    def test_supported_architectures(self):
        self.assertEqual('aarch64',installer.architecture('arm64'))
        self.assertEqual('x86_64',installer.architecture('x86_64'))

    def test_runtime_version_mismatch_blocks_launch(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from launcher import validate_background_config
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "vendor").mkdir()
            (root / "requirements.txt").write_text("MaaFw==5.14.3\n", encoding="utf-8")
            (root / "vendor/manifest.json").write_text(json.dumps({"maafw_version": "5.12.3"}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "完整包"):
                validate_background_config(root)

    def test_controller_uses_native_window_id(self):
        controller=MagicMock()
        with patch.object(mac,'require_permissions'), patch.object(mac,'MacOSController',return_value=controller) as factory:
            self.assertIs(controller,mac.connect_window(SimpleNamespace(hwnd=81)))
            self.assertEqual(81,factory.call_args.kwargs['window_id'])
            self.assertEqual(mac.MaaMacOSInputMethodEnum.PostToPid,factory.call_args.kwargs['input_method'])


if __name__ == '__main__':
    unittest.main()
