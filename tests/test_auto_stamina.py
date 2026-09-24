from __future__ import annotations

import json
import struct
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
        self.overrides = []

    def post_task(self, entry, _override=None):
        self.entries.append(entry)
        self.overrides.append(_override)
        return _Job(next(self._results))


class AutoStaminaTests(unittest.TestCase):
    def test_close_uses_button_center_and_verifies_disappearance(self):
        for close in ('通用自动补体关闭恢复体力界面', '通用自动补体无可用来源关闭'):
            node = self.pipeline[close]
            dx, dy, dw, dh = node['target_offset']
            # Logged match 60x58: all possible random clicks stay in its center.
            self.assertEqual((24, 23, 12, 12), (dx, dy, 60+dw, 58+dh))
            self.assertEqual(3, node['max_hit'])
            wait = self.pipeline[node['next'][0]]
            self.assertEqual(close, wait['next'][0])
            absent = self.pipeline[wait['next'][1]]
            self.assertTrue(absent['inverse'])
            self.assertEqual('Common/AutoStamina/recover_stamina_title.png', absent['template'])

    def test_use_region_fits_template_and_logged_batch_is_accepted(self):
        for amount in (10, 50, 100):
            for prefix in ('通用自动补体', '通用自动补体向下后'):
                node = self.pipeline[f'{prefix}单次使用{amount}体力']
                # PNG stores width and height in its first (IHDR) chunk.
                with (RESOURCE_DIR / 'image' / node['template']).open('rb') as template:
                    header = template.read(24)
                self.assertEqual(b'\x89PNG\r\n\x1a\n', header[:8])
                self.assertEqual(b'IHDR', header[12:16])
                tw, th = struct.unpack('>II', header[16:24])
                dx, dy, dw, dh = node['roi_offset']
                # Smallest title observed in the failure: 88 x 28, at (183,846).
                width, height = 88 + dw, 28 + dh
                self.assertGreaterEqual(width, tw)
                self.assertGreaterEqual(height, th)
                self.assertLess(height, 130)  # Cannot reach the adjacent row.
                self.assertLessEqual(183 + dx + width, 720)
                # Logged actual single-use caption at (526,871) remains inside.
                self.assertTrue(183 + dx <= 526 < 183 + dx + width)
                self.assertTrue(846 + dy <= 871 < 846 + dy + height)
                batch = self.pipeline[f'{prefix}批量使用{amount}体力']
                self.assertLessEqual(batch['threshold'], .839045)

    def test_items_and_actions_are_bound_to_the_same_row(self):
        for amount in (10, 50, 100):
            for prefix in ('通用自动补体', '通用自动补体向下后'):
                item_name = f'{prefix}查找{amount}体力'
                item = self.pipeline[item_name]
                self.assertEqual('OCR', item['recognition'])
                self.assertEqual(f'^{amount}体力$', item['expected'])
                self.assertEqual('march_zh', item['model'])
                batch = self.pipeline[f'{prefix}批量使用{amount}体力']
                self.assertEqual(item_name, batch['roi'])
                self.assertEqual('march_zh', batch['model'])
                # Replay logged item title at (183,845), x12 at (365,876):
                # the expected quantity lies inside the relative row, while
                # the misread cooldown X4 at (186,620) lies outside it.
                dx, dy, dw, dh = batch['roi_offset']
                x, y, w, h = 183 + dx, 845 + dy, 89 + dw, 30 + dh
                self.assertTrue(x <= 365 < x+w and y <= 876 < y+h)
                self.assertFalse(x <= 186 < x+w and y <= 620 < y+h)

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
        self.assertEqual(['通用自动补体等待无来源关闭'], node['next'])
        self.assertEqual([], self.pipeline['通用自动补体确认无来源已关闭']['next'])

    def test_engine_only_retries_when_stamina_button_changed(self):
        messages: list[str] = []
        engine = AutomationEngine.__new__(AutomationEngine)
        engine.stop_event = threading.Event()
        engine.log = messages.append

        replenished = _Tasker([True, False])
        self.assertTrue(engine._try_auto_stamina(replenished))
        self.assertIsNone(replenished.overrides[0])
        self.assertEqual({'通用识别补充体力按钮': {'timeout': 1200, 'rate_limit': 200}},
                         replenished.overrides[1])
        self.assertEqual(
            ["通用自动补体", "通用识别补充体力按钮"], replenished.entries
        )

        unavailable = _Tasker([True, True])
        self.assertFalse(engine._try_auto_stamina(unavailable))
        self.assertIn("没有可领取的免费体力", messages[-1])


if __name__ == "__main__":
    unittest.main()
