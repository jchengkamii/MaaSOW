from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.custom.action.stop_auto_help import stop_auto_help


class StopAutoHelpTests(unittest.TestCase):
    def test_stop_terminates_recorded_process_and_removes_pid_file(self):
        record = {"pid": 123, "created": 456, "token": "test", "heartbeat": 1.0}
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "auto_help.pid"
            pid_path.write_text("{}", encoding="utf-8")
            with (
                patch.object(stop_auto_help, "PID_PATH", pid_path),
                patch.object(stop_auto_help, "read_process_record", return_value=record),
                patch.object(
                    stop_auto_help, "process_record_matches_process", return_value=True
                ),
                patch.object(stop_auto_help, "terminate_recorded_process", return_value=True),
                patch.object(
                    stop_auto_help, "wait_for_recorded_process_exit", return_value=True
                ),
            ):
                message = stop_auto_help.run(None, None)

            self.assertEqual("自动帮助已停止，pid=123", message)
            self.assertFalse(pid_path.exists())

    def test_stop_is_idempotent_when_process_is_not_running(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "auto_help.pid"
            pid_path.write_text("stale", encoding="utf-8")
            with (
                patch.object(stop_auto_help, "PID_PATH", pid_path),
                patch.object(stop_auto_help, "read_process_record", return_value=None),
                patch.object(
                    stop_auto_help, "process_record_matches_process", return_value=False
                ),
            ):
                message = stop_auto_help.run(None, None)

            self.assertEqual("自动帮助当前未运行", message)
            self.assertFalse(pid_path.exists())

    def test_failed_termination_keeps_pid_file_for_retry(self):
        record = {"pid": 123, "created": 456, "token": "test", "heartbeat": 1.0}
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "auto_help.pid"
            pid_path.write_text("{}", encoding="utf-8")
            with (
                patch.object(stop_auto_help, "PID_PATH", pid_path),
                patch.object(stop_auto_help, "read_process_record", return_value=record),
                patch.object(
                    stop_auto_help, "process_record_matches_process", return_value=True
                ),
                patch.object(stop_auto_help, "terminate_recorded_process", return_value=False),
            ):
                with self.assertRaisesRegex(RuntimeError, "权限一致"):
                    stop_auto_help.run(None, None)

            self.assertTrue(pid_path.exists())


if __name__ == "__main__":
    unittest.main()
