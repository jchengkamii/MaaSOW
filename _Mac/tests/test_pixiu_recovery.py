import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from agent.custom.action.auto_pixiu import Pixiu


class RecoveryTests(unittest.TestCase):
    def flow(self):
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock()
        flow.screenshot = Mock(return_value=np.zeros((1326, 720, 3), dtype=np.uint8))
        flow.click = Mock()
        flow.pause = Mock()
        flow.pipeline = Mock(return_value=True)
        flow.record_panel_failure = Mock()
        return flow

    def test_missing_bubble_panel_precedes_background_target(self):
        flow = self.flow()
        flow.ocr = Mock(return_value=[SimpleNamespace(text='藏宝灵貅')])
        flow.templates = Mock(return_value=[])
        flow.dispatch_panel_visible = Mock(return_value=True)
        flow.activity_visible = Mock(return_value=False)
        self.assertEqual('出征弹窗', flow.recovery_state())
        flow.click.assert_not_called()

    def test_activity_precedes_target_text(self):
        flow = self.flow()
        flow.ocr = Mock(return_value=[SimpleNamespace(text='藏宝灵貅')])
        flow.templates = Mock(return_value=[])
        flow.dispatch_panel_visible = Mock(return_value=False)
        flow.activity_visible = Mock(return_value=True)
        self.assertEqual('活动界面', flow.recovery_state())

    def test_close_switches_positions_then_common_return(self):
        flow = self.flow()
        flow.recovery_state = Mock(side_effect=['出征弹窗'] * 4 + ['大世界默认态'] * 2)
        flow.recover_world()
        self.assertEqual(3, flow.click.call_count)
        self.assertEqual(3, len({call.args for call in flow.click.call_args_list}))
        flow.pipeline.assert_called_once_with('通用行军进入大地图')
        flow.record_panel_failure.assert_not_called()

    def test_persistent_failure_is_bounded_and_saves_frame(self):
        flow = self.flow()
        flow.recovery_state = Mock(return_value='目标弹窗')
        with self.assertRaises(RuntimeError):
            flow.recover_world()
        self.assertEqual(10, flow.recovery_state.call_count)
        flow.record_panel_failure.assert_called_once()

    def test_panel_fallback_needs_button_and_number(self):
        flow = self.flow()
        flow.ocr = Mock(return_value=[])
        flow.slot_number = Mock(return_value=True)
        self.assertFalse(flow.dispatch_panel_visible(flow.screenshot()))
        flow.slot_number.assert_not_called()
        flow.ocr.return_value = [SimpleNamespace(text='出征')]
        flow.slot_number.return_value = False
        self.assertFalse(flow.dispatch_panel_visible(flow.screenshot()))

    def test_title_transition_retries_without_reclicking_tab(self):
        flow = self.flow()
        flow.open_activity = Mock()
        flow.find_activity_tab = Mock()
        flow.region_text = Mock(side_effect=[False, False, True, True, True])
        flow.locate(None)
        self.assertEqual(2, flow.find_activity_tab.call_count)
        flow.record_panel_failure.assert_not_called()
