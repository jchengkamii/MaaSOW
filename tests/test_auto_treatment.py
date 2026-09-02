from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import numpy as np

from app_core import CASES_DIR, RESOURCE_DIR, CaseLoader
from cases.auto_treatment.auto_treatment import (
    _crop_changed,
    _parse_treatment_seconds,
    detect_treatment_rows,
)
from cases.auto_treatment import auto_treatment_cycle


class AutoTreatmentTests(unittest.TestCase):
    def test_case_is_registered_with_thirty_minute_target(self):
        case = next(case for case in CaseLoader().load() if case.id == "auto_treatment")
        self.assertEqual("python", case.handler)
        self.assertEqual("cases.auto_treatment.auto_treatment_cycle:run", case.extension)
        self.assertEqual(1800, case.parameters["target_seconds"])
        self.assertEqual(10.0, case.parameters["poll_interval"])
        self.assertEqual(3, case.parameters["empty_confirmations"])
        self.assertFalse(case.default_checked)
        self.assertTrue((CASES_DIR / "auto_treatment" / "auto_treatment.py").is_file())

    def test_pipeline_reuses_radar_return_assets_and_has_strict_target(self):
        pipeline = json.loads(
            (RESOURCE_DIR / "pipeline" / "auto_treatment.json").read_text(
                encoding="utf-8"
            )
        )
        navigation = pipeline["自动治疗返回主城或大世界"]
        self.assertEqual("自动治疗确认内城", navigation["next"][0])
        self.assertEqual("自动治疗确认大世界", navigation["next"][1])
        yellow = pipeline["自动治疗点击黄色返回"]
        self.assertIn("game/auto_radar/return_yellow_reference.png", yellow["template"])

        time_node = pipeline["自动治疗时间超过30分钟"]
        self.assertEqual("OCR", time_node["recognition"])
        self.assertTrue(time_node["only_rec"])
        self.assertNotRegex("00:30:00", time_node["expected"])
        reaches_node = pipeline["自动治疗时间达到30分钟"]
        self.assertRegex("00:30:00", reaches_node["expected"])
        close_node = pipeline["自动治疗关闭治疗界面"]
        self.assertEqual([662, 163, 8, 8], close_node["target"])

    def test_treatment_assets_and_ocr_model_exist(self):
        image_dir = RESOURCE_DIR / "image" / "game" / "auto_treatment"
        for name in (
            "treatment_entry.png",
            "treatment_title.png",
            "treat_button.png",
            "alliance_help.png",
            "treatment_close.png",
            "treatment_running.png",
            "treatment_in_progress.png",
            "treatment_complete.png",
        ):
            self.assertTrue((image_dir / name).is_file(), name)
        model_dir = RESOURCE_DIR / "model" / "ocr"
        for name in ("det.onnx", "rec.onnx", "keys.txt"):
            self.assertTrue((model_dir / name).is_file(), name)

    def test_visible_rows_are_sorted_top_first(self):
        image = np.zeros((1315, 720, 3), dtype=np.uint8)
        image[600:650, 490:535] = (220, 130, 40)
        image[735:785, 490:535] = (220, 130, 40)
        rows = detect_treatment_rows(image)
        self.assertEqual(2, len(rows))
        self.assertLess(rows[0].y, rows[1].y)
        self.assertTrue(all(row.minus_x < row.plus_x for row in rows))

    def test_count_change_ignores_identical_crops(self):
        before = np.zeros((40, 80, 3), dtype=np.uint8)
        after = before.copy()
        self.assertFalse(_crop_changed(before, after))
        after[10:20, 20:30] = 255
        self.assertTrue(_crop_changed(before, after))

    def test_cycle_waits_collects_and_finishes_after_stable_empty_state(self):
        class StopEvent:
            @staticmethod
            def is_set():
                return False

        class Engine:
            stop_event = StopEvent()

            @staticmethod
            def _controller_for(_target):
                return object()

            @staticmethod
            def log(_message):
                return None

        case = next(case for case in CaseLoader().load() if case.id == "auto_treatment")
        states = {
            "自动治疗确认治疗界面": [False],
            "自动治疗返回主城或大世界": [True],
            "自动治疗收取治疗完成": [False, False, True, False, False, False, False],
            "自动治疗点击治疗入口": [True, False, False, False, False, False],
            "自动治疗等待治疗界面": [True],
            "自动治疗点击仙盟互助": [True],
            "自动治疗关闭治疗界面": [True],
            "自动治疗等待返回主界面": [True],
            "自动治疗确认正在治疗图标": [True, False, False, False],
            "自动治疗确认内城": [True, True, True],
        }

        def fake_pipeline(_engine, entry, _timeout):
            values = states.get(entry)
            return values.pop(0) if values else False

        with (
            patch.object(auto_treatment_cycle, "_run_pipeline", fake_pipeline),
            patch.object(
                auto_treatment_cycle,
                "_adjust_or_reuse_and_start_treatment",
                return_value=(4, 1800, False),
            ),
            patch.object(auto_treatment_cycle, "_wait_or_stop", return_value=None),
        ):
            result = auto_treatment_cycle.run(Engine(), case)

        self.assertIn("自动治疗完成", result)
        self.assertIn("共开始 1 批治疗", result)
        self.assertIn("调整弟子数量 4 次", result)

    def test_cycle_does_not_finish_while_started_treatment_is_uncollected(self):
        class StopEvent:
            @staticmethod
            def is_set():
                return False

        class Engine:
            stop_event = StopEvent()

            @staticmethod
            def _controller_for(_target):
                return object()

            @staticmethod
            def log(_message):
                return None

        case = next(case for case in CaseLoader().load() if case.id == "auto_treatment")
        calls = {"completed": 0, "entry_clicked": False}

        def fake_pipeline(_engine, entry, _timeout):
            if entry == "自动治疗确认治疗界面":
                return False
            if entry == "自动治疗返回主城或大世界":
                return True
            if entry == "自动治疗点击治疗入口":
                if not calls["entry_clicked"]:
                    calls["entry_clicked"] = True
                    return True
                return False
            if entry == "自动治疗等待治疗界面":
                return True
            if entry in ("自动治疗点击仙盟互助", "自动治疗关闭治疗界面"):
                return True
            if entry == "自动治疗确认正在治疗图标":
                return False
            if entry == "自动治疗收取治疗完成":
                calls["completed"] += 1
                # 开始治疗后连续漏识别多轮，随后才识别到完成头像。
                return calls["completed"] == 7
            if entry == "自动治疗确认内城":
                return calls["completed"] > 7
            return False

        with (
            patch.object(auto_treatment_cycle, "_run_pipeline", fake_pipeline),
            patch.object(
                auto_treatment_cycle,
                "_adjust_or_reuse_and_start_treatment",
                return_value=(2, 1800, False),
            ),
            patch.object(auto_treatment_cycle, "_wait_or_stop", return_value=None),
        ):
            result = auto_treatment_cycle.run(Engine(), case)

        self.assertGreaterEqual(calls["completed"], 10)
        self.assertIn("共开始 1 批治疗", result)

    def test_exact_thirty_minutes_is_target_and_unchanged_time_is_reused(self):
        self.assertEqual(1800, _parse_treatment_seconds("00:30:00"))

        class Engine:
            @staticmethod
            def log(_message):
                return None

        engine = Engine()
        with (
            patch.object(
                auto_treatment_cycle,
                "_read_treatment_seconds",
                return_value=1800,
            ),
            patch.object(
                auto_treatment_cycle,
                "_run_pipeline",
                return_value=True,
            ) as pipeline,
            patch.object(
                auto_treatment_cycle,
                "_adjust_and_start_treatment",
            ) as adjust,
        ):
            result = auto_treatment_cycle._adjust_or_reuse_and_start_treatment(
                engine, object(), 1800, 0.4, 1.5, 2000, 1800
            )

        self.assertEqual((0, 1800, True), result)
        adjust.assert_not_called()
        pipeline.assert_called_once_with(engine, "自动治疗点击治疗按钮", 1.5)

    def test_first_batch_at_exact_thirty_minutes_does_not_click_plus_or_minus(self):
        controller = object()
        with (
            patch.object(
                auto_treatment_cycle,
                "detect_treatment_rows",
                return_value=[object()],
            ),
            patch.object(auto_treatment_cycle, "_screenshot", return_value=np.zeros((1, 1, 3))),
            patch.object(auto_treatment_cycle, "_time_exceeds_target", return_value=False),
            patch.object(auto_treatment_cycle, "_time_reaches_target", return_value=True),
            patch.object(auto_treatment_cycle, "_read_treatment_seconds", return_value=1800),
            patch.object(auto_treatment_cycle, "_run_pipeline", return_value=True),
            patch.object(auto_treatment_cycle, "_click_and_detect_change") as click,
        ):
            result = auto_treatment_cycle._adjust_and_start_treatment(
                object(), controller, 1800, 0.4, 1.5, 2000
            )

        self.assertEqual((0, True, 1800), result)
        click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
