from __future__ import annotations

import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from agent.core import CaseLoader, PROJECT_DIR, RESOURCE_DIR
from agent.custom.action.run_configured_case import (
    WORKER_SCRIPT,
    auto_stamina_enabled,
    parse_case_id,
    worker_command,
    worker_command_with_options,
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
            self.assertFalse(case.auto_stamina)
            self.assertNotIn("option", task)

        self.assertNotIn("option", generated)

    def test_only_opted_in_case_gets_compact_auto_stamina_checkbox(self):
        base_case = CaseLoader().load()[0]
        opted_in_case = replace(base_case, auto_stamina=True)
        with patch("generate_interface.CaseLoader.load", return_value=[opted_in_case]):
            generated = generate()

        task = generated["task"][0]
        self.assertEqual(["自动补体"], task["option"])
        auto_stamina = generated["option"]["自动补体"]
        self.assertEqual("checkbox", auto_stamina["type"])
        self.assertEqual("", auto_stamina["label"])
        self.assertNotIn("description", auto_stamina)
        self.assertEqual([], auto_stamina["default_case"])
        self.assertEqual(1, len(auto_stamina["cases"]))
        self.assertEqual("自动补体", auto_stamina["cases"][0]["label"])
        self.assertNotIn("description", auto_stamina["cases"][0])
        override = auto_stamina["cases"][0]["pipeline_override"]
        self.assertTrue(override["通用自动补体开关"]["enabled"])

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

        enabled_command = worker_command_with_options("auto_radar", True)
        self.assertEqual("--auto-stamina", enabled_command[-1])

    def test_agent_reads_auto_stamina_toggle_from_merged_pipeline(self):
        class Context:
            @staticmethod
            def get_node_data(name):
                self.assertEqual("通用自动补体开关", name)
                return {"recognition": "DirectHit", "enabled": True}

        self.assertTrue(auto_stamina_enabled(Context()))

        class MissingContext:
            @staticmethod
            def get_node_data(_name):
                return None

        self.assertFalse(auto_stamina_enabled(MissingContext()))


if __name__ == "__main__":
    unittest.main()
