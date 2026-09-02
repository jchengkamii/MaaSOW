from __future__ import annotations

import json
import unittest

from agent.core import CaseLoader, PROJECT_DIR, RESOURCE_DIR
from agent.custom.action.run_configured_case import (
    WORKER_SCRIPT,
    parse_case_id,
    worker_command,
)
from generate_interface import generate


class MxuIntegrationTests(unittest.TestCase):
    def test_interface_is_project_interface_v2(self):
        interface = json.loads((PROJECT_DIR / "interface.json").read_text(encoding="utf-8"))
        self.assertEqual(2, interface["interface_version"])
        self.assertEqual("MaaSOW", interface["name"])
        self.assertEqual("resource/app_icon.png", interface["icon"])
        self.assertTrue((PROJECT_DIR / interface["icon"]).is_file())
        self.assertEqual("Win32", interface["controller"][0]["type"])
        self.assertEqual("^九霄仙府$", interface["controller"][0]["win32"]["window_regex"])
        self.assertEqual(
            "^Chrome_WidgetWin_0$",
            interface["controller"][0]["win32"]["class_regex"],
        )
        self.assertEqual("./.venv/Scripts/python.exe", interface["agent"]["child_exec"])
        self.assertEqual(["resource/base"], interface["resource"][0]["path"])
        self.assertEqual(["-u", "./agent/main.py"], interface["agent"]["child_args"])
        self.assertIn("resource/interface.tasks.json", interface["import"])

    def test_saved_preview_device_is_game_window(self):
        config_path = PROJECT_DIR / "config" / "mxu-MaaSOW.json"
        if not config_path.is_file():
            self.skipTest("MXU local configuration is not available")

        config = json.loads(
            config_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            "九霄仙府", config["instances"][0]["savedDevice"]["windowName"]
        )

    def test_every_external_case_becomes_an_mxu_task(self):
        cases = [case for case in CaseLoader().load() if case.enabled]
        generated = generate()
        self.assertEqual([case.id for case in cases], [task["name"] for task in generated["task"]])
        for case, task in zip(cases, generated["task"]):
            self.assertEqual("MXU执行外部用例", task["entry"])
            param = task["pipeline_override"]["MXU执行外部用例"]["custom_action_param"]
            self.assertEqual(case.id, param["case_id"])

    def test_mxu_pipeline_uses_agent_custom_action(self):
        pipeline = json.loads(
            (
                RESOURCE_DIR
                / "pipeline"
                / "Interface"
                / "RunConfiguredCase.json"
            ).read_text(encoding="utf-8")
        )
        node = pipeline["MXU执行外部用例"]
        self.assertEqual("Custom", node["action"])
        self.assertEqual("RunConfiguredCase", node["custom_action"])

    def test_agent_case_parameter_parser(self):
        self.assertEqual("auto_radar", parse_case_id('{"case_id":"auto_radar"}'))
        self.assertEqual("auto_radar", parse_case_id('"auto_radar"'))

    def test_agent_delegates_cases_to_independent_worker(self):
        command = worker_command("auto_radar")
        self.assertTrue(WORKER_SCRIPT.is_file())
        self.assertEqual("-u", command[1])
        self.assertEqual(["-m", "agent.worker"], command[2:4])
        self.assertEqual(["--case-id", "auto_radar"], command[4:])


if __name__ == "__main__":
    unittest.main()
