from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from agent import macos_platform as mac
from agent.custom.action.auto_help import auto_help_process as process
from agent.custom.action.auto_help import automation_mutex as mutex

class MacAdapterTests(unittest.TestCase):
    def test_launcher_rejects_foreground_input(self):
        from launcher import validate_background_config
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            interface = {"controller": [{"type": "MacOS", "macos": {"input": "PostToPid"}}]}
            (root / "interface.json").write_text(json.dumps(interface), encoding="utf-8")
            validate_background_config(root)
            (root / "config/macos.json").write_text('{"input_method":"GlobalEvent"}', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "PostToPid"):
                validate_background_config(root)
            (root / "config/macos.json").unlink()
            interface["controller"][0]["macos"]["input"] = "GlobalEvent"
            (root / "interface.json").write_text(json.dumps(interface), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "PostToPid"):
                validate_background_config(root)

    def test_agent_rejects_foreground_input_before_creating_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config/macos.json").write_text('{"input_method":"GlobalEvent"}', encoding="utf-8")
            with patch.object(mac, "ROOT", root), patch.object(mac, "MacOSController") as factory:
                with self.assertRaisesRegex(ValueError, "PostToPid"):
                    mac.connect_window(SimpleNamespace(hwnd=81))
                factory.assert_not_called()

    def test_native_mxu_exit_cleans_up_helper(self):
        from launcher import run_mxu
        with patch("launcher.validate_background_config"), patch("tools.install_mxu.verify_installed"), patch("launcher.subprocess.Popen") as launch, patch("agent.custom.action.stop_auto_help.stop_auto_help.run", return_value="stopped") as stop:
            launch.return_value.wait.return_value = 0
            self.assertEqual(0, run_mxu(mac.ROOT))
            self.assertEqual([str(mac.ROOT / "mxu")], launch.call_args.args[0])
            self.assertEqual(mac.ROOT, launch.call_args.kwargs["cwd"])
            stop.assert_called_once_with(None, None)

    def test_diagnostic_png_preserves_bgr_pixels(self):
        import numpy as np
        import struct
        import zlib
        from tools.diagnose import save_png
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"image.png"
            save_png(path, np.array([[[1, 2, 3], [4, 5, 6]]], dtype=np.uint8))
            data = path.read_bytes()
            self.assertEqual(b"\x89PNG\r\n\x1a\n", data[:8])
            index = 8
            while index < len(data):
                size = struct.unpack(">I", data[index:index+4])[0]
                if data[index+4:index+8] == b"IDAT":
                    self.assertEqual(bytes([0, 3, 2, 1, 6, 5, 4]), zlib.decompress(data[index+8:index+8+size]))
                    break
                index += size + 12
            else:
                self.fail("No PNG pixel data")

    def test_window_lookup_rejects_ambiguous_titles(self):
        windows = [SimpleNamespace(hwnd=1, window_name="九霄仙府"), SimpleNamespace(hwnd=2, window_name="九霄仙府")]
        with patch.object(mac, "require_permissions"), patch.object(mac.Toolkit, "find_desktop_windows", return_value=windows):
            with self.assertRaisesRegex(RuntimeError, "多个"):
                mac.find_game_window()

    def test_window_lookup_does_not_use_windows_class_names(self):
        game = SimpleNamespace(hwnd=91, window_name="九霄仙府", class_name="com.tencent.xinWeChat")
        with patch.object(mac, "require_permissions"), patch.object(mac.Toolkit, "find_desktop_windows", return_value=[game]):
            self.assertIs(game, mac.find_game_window())

    def test_permissions_fail_before_connecting(self):
        with patch.object(mac.sys, "platform", "darwin"), patch.object(mac.Toolkit, "macos_check_permission", return_value=False), patch.object(mac.Toolkit, "macos_request_permission") as request:
            with self.assertRaisesRegex(RuntimeError, "屏幕录制、辅助功能"):
                mac.require_permissions(request=True)
            self.assertEqual(2, request.call_count)

    def test_controller_uses_native_id_and_720_short_side(self):
        controller = MagicMock()
        with patch.object(mac, "require_permissions"), patch.object(mac, "MacOSController", return_value=controller) as factory:
            self.assertIs(controller, mac.connect_window(SimpleNamespace(hwnd=81)))
            self.assertEqual(81, factory.call_args.kwargs["window_id"])
            self.assertEqual(mac.MaaMacOSInputMethodEnum.PostToPid, factory.call_args.kwargs["input_method"])
            controller.set_screenshot_target_short_side.assert_called_once_with(720)

    def test_stale_record_cannot_terminate_reused_pid(self):
        record = {"pid": 123, "created": 456}
        with patch.object(process, "process_creation_time", return_value=789), patch.object(process.psutil, "Process") as factory:
            self.assertFalse(process.terminate_recorded_process(record))
            factory.assert_not_called()

    def test_recorded_child_can_be_stopped(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            with tempfile.TemporaryDirectory() as directory:
                record = process.write_process_record(Path(directory)/"pid.json", child.pid, "test")
                self.assertTrue(process.process_record_matches_process(record))
                self.assertTrue(process.terminate_recorded_process(record))
                child.wait(timeout=5)
                self.assertFalse(process.process_record_matches_process(record))
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)

    def test_mutex_excludes_another_process_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory)/"test.lock"
            code = ("from pathlib import Path; from agent.custom.action.auto_help import automation_mutex as m; "
                    f"m.LOCK_PATH=Path({str(lock)!r}); lock=m.AutomationMutex(); "
                    "acquired=lock.acquire(timeout=0.2); lock.close(); raise SystemExit(0 if acquired else 2)")
            with patch.object(mutex, "LOCK_PATH", lock):
                owner = mutex.AutomationMutex()
                self.assertTrue(owner.acquire(timeout=0))
                try:
                    result = subprocess.run([sys.executable, "-c", code], cwd=mac.ROOT, timeout=10)
                    self.assertEqual(2, result.returncode)
                finally:
                    owner.close()
                result = subprocess.run([sys.executable, "-c", code], cwd=mac.ROOT, timeout=10)
                self.assertEqual(0, result.returncode)

if __name__ == "__main__":
    unittest.main()
