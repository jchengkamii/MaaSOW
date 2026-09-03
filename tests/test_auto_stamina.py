from __future__ import annotations

import json
import threading
import unittest

from agent.core import AutomationEngine, RESOURCE_DIR


class _Job:
    def __init__(self, succeeded: bool):
        self.succeeded = succeeded

    def wait(self):
        return self


class _Tasker:
    def __init__(self, results: list[bool]):
        self._results = iter(results)
        self.entries: list[str] = []

    def post_task(self, entry, _override=None):
        self.entries.append(entry)
        return _Job(next(self._results))


class AutoStaminaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline_path = (
            RESOURCE_DIR / "pipeline" / "Common" / "AutoStamina.json"
        )
        cls.pipeline = json.loads(cls.pipeline_path.read_text(encoding="utf-8"))

    def test_common_pipeline_and_templates_exist(self):
        self.assertIn("通用自动补体", self.pipeline)
        image_dir = RESOURCE_DIR / "image" / "Common" / "AutoStamina"
        expected = {
            "replenish_stamina_button.png",
            "recover_stamina_title.png",
            "recover_stamina_close.png",
            "claim_enabled.png",
            "use_enabled.png",
            "reward_title.png",
            "stamina_item_10.png",
            "stamina_item_50.png",
            "stamina_item_100.png",
        }
        self.assertEqual(expected, {path.name for path in image_dir.glob("*.png")})

    def test_free_source_priority_and_batch_before_single_use(self):
        selector = self.pipeline["通用自动补体选择来源"]["next"]
        self.assertEqual(
            [
                "通用自动补体收取逍遥剑仙",
                "通用自动补体收取每日75体力",
                "通用自动补体查找10体力",
                "通用自动补体查找50体力",
                "通用自动补体查找100体力",
                "通用自动补体向下查找100体力",
            ],
            selector,
        )
        for amount in (10, 50, 100):
            choices = self.pipeline[f"通用自动补体查找{amount}体力"]["next"]
            self.assertEqual(f"通用自动补体批量使用{amount}体力", choices[0])
            self.assertEqual(f"通用自动补体单次使用{amount}体力", choices[1])
            batch = self.pipeline[choices[0]]
            self.assertEqual("OCR", batch["recognition"])
            self.assertEqual("^[xX][1-9]\\d*$", batch["expected"])

            scrolled_choices = self.pipeline[
                f"通用自动补体向下后查找{amount}体力"
            ]["next"]
            self.assertEqual(
                f"通用自动补体向下后批量使用{amount}体力",
                scrolled_choices[0],
            )
            self.assertEqual(
                f"通用自动补体向下后单次使用{amount}体力",
                scrolled_choices[1],
            )

    def test_pipeline_contains_no_purchase_action_or_template(self):
        serialized = json.dumps(self.pipeline, ensure_ascii=False)
        self.assertNotIn("购买并使用", serialized)
        self.assertNotIn("礼包", serialized)
        self.assertNotIn("支付", serialized)
        allowed_click_templates = {
            "Common/AutoStamina/replenish_stamina_button.png",
            "Common/AutoStamina/claim_enabled.png",
            "Common/AutoStamina/use_enabled.png",
            "Common/AutoStamina/reward_title.png",
            "Common/AutoStamina/recover_stamina_close.png",
        }
        for name, node in self.pipeline.items():
            if node.get("action") != "Click" or node.get("recognition") == "OCR":
                continue
            self.assertIn(node.get("template"), allowed_click_templates, name)

    def test_no_free_source_closes_dialog(self):
        node = self.pipeline["通用自动补体无可用来源关闭"]
        self.assertEqual("Common/AutoStamina/recover_stamina_close.png", node["template"])
        self.assertEqual("Click", node["action"])
        self.assertNotIn("next", node)

    def test_engine_only_retries_when_stamina_button_changed(self):
        messages: list[str] = []
        engine = AutomationEngine.__new__(AutomationEngine)
        engine.stop_event = threading.Event()
        engine.log = messages.append

        replenished = _Tasker([True, False])
        self.assertTrue(engine._try_auto_stamina(replenished))
        self.assertEqual(
            ["通用自动补体", "通用识别补充体力按钮"], replenished.entries
        )

        unavailable = _Tasker([True, True])
        self.assertFalse(engine._try_auto_stamina(unavailable))
        self.assertIn("没有可领取的免费体力", messages[-1])


if __name__ == "__main__":
    unittest.main()
