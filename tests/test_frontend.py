from __future__ import annotations

import json
import unittest
from pathlib import Path

from app_core import AutomationEngine, CASES_DIR, PROJECT_DIR, RESOURCE_DIR, CaseLoader
from gui_app import connection_display


def load_pipeline_nodes() -> dict:
    nodes: dict = {}
    for path in sorted((RESOURCE_DIR / "pipeline").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        duplicates = nodes.keys() & data.keys()
        if duplicates:
            raise AssertionError(f"Pipeline 节点重名：{sorted(duplicates)}")
        nodes.update(data)
    return nodes


class FrontendConfigurationTests(unittest.TestCase):
    def test_initial_cases_are_valid_and_sorted(self):
        cases = CaseLoader().load()
        self.assertEqual(9, len(cases))
        self.assertEqual(len(cases), len({case.id for case in cases}))
        self.assertEqual(cases, sorted(cases, key=lambda case: (case.order, case.id)))
        self.assertTrue(all(case.enabled for case in cases))

    def test_pipeline_entries_exist(self):
        pipeline = load_pipeline_nodes()
        for case in CaseLoader().load():
            if case.handler == "pipeline":
                self.assertIn(case.pipeline_entry, pipeline, case.id)

    def test_pipeline_is_split_by_case_and_references_are_valid(self):
        pipeline_dir = RESOURCE_DIR / "pipeline"
        self.assertFalse((pipeline_dir / "main.json").exists())
        expected = {
            "auto_help.json",
            "auto_radar.json",
            "auto_treatment.json",
            "check_game_state.json",
            "close_face_popups.json",
            "mxu.json",
            "open_game.json",
            "open_profile.json",
            "verify_profile.json",
        }
        self.assertEqual(expected, {path.name for path in pipeline_dir.glob("*.json")})

        pipeline = load_pipeline_nodes()
        for node_name, node in pipeline.items():
            for edge in ("next", "on_error"):
                for target in node.get(edge, []):
                    target_name = target.split("]", 1)[-1] if target.startswith("[") else target
                    self.assertIn(target_name, pipeline, f"{node_name} -> {target}")

    def test_runtime_does_not_save_debug_screenshots(self):
        options = json.loads(
            (PROJECT_DIR / "config" / "maa_option.json").read_text(encoding="utf-8")
        )
        self.assertFalse(options["save_draw"])
        self.assertFalse(options["save_on_error"])

    def test_case_directory_contains_only_expected_active_json(self):
        active = sorted(CASES_DIR.rglob("*.json"))
        self.assertEqual(9, len(active))
        self.assertFalse(list(CASES_DIR.glob("*.json")))
        for path in active:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(f"{data['id']}.json", path.name)
            self.assertEqual(data["id"], path.parent.name)

    def test_connection_status_colors(self):
        self.assertEqual(
            ("● 未找到微信", "Connection.Red.TLabel"),
            connection_display({"wechat_main": False, "wechat_panel": False, "game": False}),
        )
        self.assertEqual(
            "Connection.Yellow.TLabel",
            connection_display({"wechat_main": True, "wechat_panel": False, "game": False})[1],
        )
        self.assertEqual(
            "Connection.Green.TLabel",
            connection_display({"wechat_main": True, "wechat_panel": False, "game": True})[1],
        )

    def test_open_game_waits_for_main_screen(self):
        case = next(case for case in CaseLoader().load() if case.id == "open_game")
        self.assertEqual(120, case.wait_timeout)
        self.assertEqual("game", case.wait_for_window)
        self.assertIsNone(case.postcondition_entry)
        pipeline = load_pipeline_nodes()
        wait_node = pipeline["等待游戏主界面加载完成"]
        self.assertEqual(120000, wait_node["timeout"])
        self.assertEqual(["内城主界面左下特征"], wait_node["next"])
        left_node = pipeline["内城主界面左下特征"]
        right_node = pipeline["内城主界面右下特征"]
        self.assertEqual(2, len(left_node["template"]))
        self.assertEqual(["内城主界面右下特征"], left_node["next"])
        self.assertEqual(2, len(right_node["template"]))
        self.assertNotIn("avatar_button.png", json.dumps(wait_node, ensure_ascii=False))
        for template in left_node["template"] + right_node["template"]:
            self.assertTrue((RESOURCE_DIR / "image" / template).is_file())

    def test_close_face_popups_runs_after_open_game_and_asserts_inner_city(self):
        cases = CaseLoader().load()
        open_index = next(i for i, case in enumerate(cases) if case.id == "open_game")
        close_index = next(
            i for i, case in enumerate(cases) if case.id == "close_face_popups"
        )
        check_index = next(
            i for i, case in enumerate(cases) if case.id == "check_game_state"
        )
        self.assertLess(open_index, close_index)
        self.assertLess(close_index, check_index)
        close_case = cases[close_index]
        self.assertEqual("关闭拍脸弹窗并等待内城", close_case.pipeline_entry)

        pipeline = load_pipeline_nodes()
        root = pipeline["关闭拍脸弹窗并等待内城"]
        self.assertIn("识别并关闭拍脸弹窗第1次", root["next"])
        self.assertIn("内城主界面左下特征", root["next"])
        self.assertIn("点击拍脸遮罩空白区域第1次", root["next"])
        close_node = pipeline["识别并关闭拍脸弹窗第1次"]
        self.assertEqual(3, len(close_node["template"]))
        for template in close_node["template"]:
            self.assertTrue((RESOURCE_DIR / "image" / template).is_file())
        self.assertNotIn("关闭拍脸弹窗并等待内城", close_node["next"])
        blank_nodes = [
            pipeline[f"点击拍脸遮罩空白区域第{index}次"]
            for index in range(1, 4)
        ]
        self.assertTrue(all(node["post_delay"] >= 3000 for node in blank_nodes))
        self.assertTrue(
            all(
                "关闭拍脸弹窗并等待内城" not in node["next"]
                for node in blank_nodes
            )
        )

    def test_current_wechat_miniprogram_button_coordinate(self):
        self.assertEqual((34, 440), AutomationEngine.MINIPROGRAM_BUTTON)

    def test_game_input_does_not_seize_physical_mouse(self):
        mouse, keyboard = AutomationEngine._input_methods_for("game")
        self.assertEqual("SendMessage", mouse.name)
        self.assertEqual("PostMessage", keyboard.name)
        wechat_mouse, _wechat_keyboard = AutomationEngine._input_methods_for(
            "wechat_main"
        )
        self.assertEqual("Seize", wechat_mouse.name)

    def test_auto_help_is_an_opt_in_background_case(self):
        case = next(case for case in CaseLoader().load() if case.id == "auto_help")
        self.assertEqual("python", case.handler)
        self.assertEqual("cases.auto_help.auto_help:run", case.extension)
        self.assertFalse(case.default_checked)
        self.assertEqual("后台辅助", case.group)
        self.assertEqual(1.0, case.parameters["repeat_cooldown"])
        case_dir = CASES_DIR / "auto_help"
        self.assertTrue((case_dir / "auto_help.py").is_file())
        self.assertTrue((case_dir / "auto_help_worker.py").is_file())
        self.assertTrue((case_dir / "auto_help_process.py").is_file())
        self.assertTrue((case_dir / "automation_mutex.py").is_file())

        pipeline = load_pipeline_nodes()
        detect = pipeline["自动帮助按钮特征"]
        click = pipeline["识别并点击自动帮助按钮"]
        self.assertEqual("game/auto_help_button.png", detect["template"])
        self.assertEqual(detect["template"], click["template"])
        self.assertEqual("Click", click["action"])
        self.assertTrue((RESOURCE_DIR / "image" / detect["template"]).is_file())

    def test_auto_radar_prioritizes_bulk_actions_and_bounds_automation(self):
        case = next(case for case in CaseLoader().load() if case.id == "auto_radar")
        self.assertEqual("pipeline", case.handler)
        self.assertEqual("game", case.controller_target)
        self.assertEqual("自动雷达", case.pipeline_entry)
        self.assertFalse(case.default_checked)

        pipeline = load_pipeline_nodes()
        root = pipeline["自动雷达"]
        self.assertEqual(
            [
                "自动雷达确认进入雷达",
                "自动雷达确认内城",
                "自动雷达确认大世界",
                "自动雷达点击黄色返回",
                "自动雷达点击蓝色返回",
            ],
            root["next"],
        )
        hall = pipeline["自动雷达点击执事堂"]
        self.assertEqual("And", hall["recognition"])
        self.assertEqual(2, len(hall["all_of"]))
        overworld = pipeline["自动雷达确认大世界"]
        self.assertEqual("And", overworld["recognition"])
        self.assertEqual(
            "game/auto_radar/return_sect_runtime.png",
            overworld["all_of"][1]["template"],
        )
        self.assertEqual(
            ["自动雷达确认内城", "自动雷达确认大世界"],
            pipeline["自动雷达等待执行返回内城"]["next"],
        )

        dispatcher = pipeline["自动雷达调度"]
        self.assertEqual("[JumpBack]自动雷达点击一键领取", dispatcher["next"][0])
        self.assertEqual("自动雷达点击一键执行", dispatcher["next"][1])
        self.assertEqual(1, pipeline["自动雷达点击一键执行"]["max_hit"])
        self.assertEqual(20, pipeline["自动雷达推进对话"]["max_hit"])
        self.assertEqual(["自动雷达确认处理完成"], dispatcher["on_error"])

        radar_dir = RESOURCE_DIR / "image" / "game" / "auto_radar"
        templates = set()
        for node in pipeline.values():
            value = node.get("template", [])
            values = value if isinstance(value, list) else [value]
            templates.update(
                item for item in values
                if isinstance(item, str) and item.startswith("game/auto_radar/")
            )
            for child in node.get("all_of", []):
                if isinstance(child, dict):
                    value = child.get("template", [])
                    templates.update(value if isinstance(value, list) else [value])
        self.assertGreaterEqual(len(templates), 20)
        for template in templates:
            self.assertTrue((RESOURCE_DIR / "image" / template).is_file(), template)
        self.assertTrue(radar_dir.is_dir())

if __name__ == "__main__":
    unittest.main()
