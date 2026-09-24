from __future__ import annotations
import unittest
from unittest.mock import Mock
import numpy as np
from agent.custom.action.march.state import MarchState as S, MarchTracker, parse_status
from agent.custom.action.march.march import March, MarchHandle, SquadRow, new_dispatched_row

class MarchTests(unittest.TestCase):
    def test_outbound_ocr_coordinate_punctuation_and_suffix(self):
        for text in ['去X：235Y.3481有', '去X:235Y:348', '去X：235Y，348']:
            self.assertEqual(S.OUTBOUND, parse_status(text))
        for text in ['去X：235', 'X：235Y.348', '去X:235Y:34800:12', '去X:Y:']:
            self.assertIsNone(parse_status(text))

    def test_added_row_survives_simultaneous_return(self):
        a, b, c = np.random.default_rng(951).random((3, 24, 24, 3))
        old = [SquadRow(a, S.RETURNING), SquadRow(b, S.RETURNING)]
        added = SquadRow(c, S.OUTBOUND)
        self.assertIs(added, new_dispatched_row(old, [old[0], added], 2))
        self.assertIs(added, new_dispatched_row(old, [added], 1))
        self.assertIsNone(new_dispatched_row(old, [old[0]], 1))
        self.assertIsNone(new_dispatched_row(old, [SquadRow(c, S.RETURNING)], 1))
        self.assertIsNone(new_dispatched_row(old, [added, added], 2))

    def test_simultaneous_return_confirmation_requires_three_frames(self):
        flow = self.make_dispatch()
        a, b, c = np.random.default_rng(952).random((3, 24, 24, 3))
        old = [SquadRow(a, S.RETURNING), SquadRow(b, S.RETURNING)]
        added = SquadRow(c, parse_status('去X：235Y.3481有'))
        flow.snapshot = Mock(side_effect=[(True, [old[0], added], 2),
                                          (True, [added], 1), (True, [added], 1)])
        handle = flow.dispatch_from_panel(queue=1, existing=old)
        self.assertIs(c, handle.avatar)
        self.assertEqual(3, flow.snapshot.call_count)
        self.assertEqual(1, sum(call.args[0] == '出征' for call in flow.text_button.call_args_list))

    def test_added_row_handles_reorder_but_not_ambiguous_or_returned_rows(self):
        a, b, c = np.random.default_rng(91).random((3, 24, 24, 3))
        old = [SquadRow(a, S.OUTBOUND), SquadRow(b, S.RETURNING)]
        added = SquadRow(c, S.OUTBOUND)
        self.assertIs(added, new_dispatched_row(old, [old[1], added, old[0]], 3))
        self.assertIsNone(new_dispatched_row(old, [old[1], added], 2))
        self.assertIsNone(new_dispatched_row(old, [old[0], old[0], added], 3))
        self.assertIsNone(new_dispatched_row(old, [*old, SquadRow(c, S.RETURNING)], 3))

    def test_third_squad_confirmed_despite_panel_portrait_mismatch(self):
        flow = self.make_dispatch()
        a, b, c = np.random.default_rng(92).random((3,24,24,3))
        old = [SquadRow(a, S.OUTBOUND), SquadRow(b, S.OUTBOUND)]
        added = SquadRow(c, S.OUTBOUND)
        flow.snapshot = Mock(return_value=(True, [old[1], added, old[0]], 3))
        original_panel_avatar = flow.panel.return_value[1][0][2].copy()
        handle = flow.dispatch_from_panel(queue=1, existing=old)
        self.assertIs(handle.avatar, c)
        np.testing.assert_array_equal(original_panel_avatar, handle.panel_avatar)
        self.assertIsNot(handle.panel_avatar, handle.avatar)
        self.assertEqual(3, flow.snapshot.call_count)
        self.assertEqual(1, sum(call.args[0] == '出征' for call in flow.text_button.call_args_list))

    def test_unknown_baseline_does_not_confirm_by_increased_count(self):
        flow = self.make_dispatch()
        flow.pre_snapshot_reliable = False
        avatar = np.random.default_rng(93).random((24,24,3))
        flow.snapshot = Mock(return_value=(True, [SquadRow(avatar, S.OUTBOUND)], 1))
        with self.assertRaises(TimeoutError):
            flow.dispatch_from_panel(queue=1, existing=[], timeout=.01)

    def test_status_does_not_accept_timers(self):
        self.assertEqual(S.OUTBOUND, parse_status('去 X:919 Y:6'))
        self.assertEqual(S.FIGHTING, parse_status('战斗中'))
        self.assertEqual(S.RETURNING, parse_status('返回'))
        for text in ('00:00:00', '00:00:16', '', '新增小队', '去', '返回 00:00:16'):
            self.assertIsNone(parse_status(text))

    def test_disappearance_requires_returning(self):
        for state in (None, S.OUTBOUND, S.FIGHTING):
            tracker = MarchTracker(state=state)
            for _ in range(5):
                self.assertFalse(tracker.observe(visible=False, status=None, reliable=True, count_decreased=True))

    def test_confirmation_resets_on_bad_frame_or_reappearance(self):
        tracker = MarchTracker(state=S.RETURNING)
        missing = dict(visible=False, status=None, reliable=True, count_decreased=True)
        self.assertFalse(tracker.observe(**missing))
        self.assertFalse(tracker.observe(visible=False, status=None, reliable=False))
        self.assertEqual(0, tracker.missing)
        self.assertFalse(tracker.observe(**missing))
        self.assertFalse(tracker.observe(visible=True, status=None, reliable=True))
        self.assertEqual(S.RETURNING, tracker.state)
        self.assertFalse(tracker.observe(**missing))
        self.assertFalse(tracker.observe(**missing))
        self.assertTrue(tracker.observe(**missing))

    def test_count_must_decrease(self):
        tracker = MarchTracker(state=S.RETURNING)
        for _ in range(5):
            self.assertFalse(tracker.observe(visible=False, status=None, reliable=True))

    def test_tracks_portrait_after_other_row_disappears(self):
        rng = np.random.default_rng(24)
        a, b = [rng.random((24, 24, 3)) for _ in range(2)]
        flow = March.__new__(March)
        flow.engine = Mock()
        flow.snapshot = Mock(side_effect=[
            (True, [SquadRow(a, S.OUTBOUND), SquadRow(b, S.RETURNING)], 2),
            (True, [SquadRow(b, S.RETURNING)], 1),
            (False, [], 0),
            (True, [], 0), (True, [], 0), (True, [], 0)])
        handle = MarchHandle(2, b, MarchTracker(), 2)
        self.assertEqual([False] * 5 + [True], [flow.poll(handle) for _ in range(6)])

    def test_ambiguous_portraits_do_not_update_state(self):
        a = np.random.default_rng(1).random((24, 24, 3))
        flow = March.__new__(March)
        flow.engine = Mock()
        flow.snapshot = Mock(return_value=(True, [SquadRow(a, S.RETURNING)] * 2, 2))
        handle = MarchHandle(1, a, MarchTracker(state=S.OUTBOUND), 2)
        self.assertFalse(flow.poll(handle))
        self.assertEqual(S.OUTBOUND, handle.tracker.state)

    def test_invalid_target_and_queue_fail_before_navigation(self):
        flow = March.__new__(March)
        flow.pipeline = Mock()
        for target, queue in ((None, None), ([10, 20], 0), ([10, 20], True), ([float('nan'), 20], 1)):
            with self.assertRaises(ValueError):
                flow.dispatch(target, queue)
        flow.pipeline.assert_not_called()

    def test_native_screenshot_recognition(self):
        import subprocess
        import sys
        from pathlib import Path
        result = subprocess.run([sys.executable, "-X", "utf8",
                                 str(Path(__file__).with_name("march_native_probe.py"))],
                                capture_output=True, encoding="utf-8", timeout=60)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def make_dispatch(self, unlocked=True):
        flow = March.__new__(March)
        avatar = np.random.default_rng(8).random((24, 24, 3))
        flow.engine = Mock()
        flow.pipeline = Mock(return_value=True)
        flow.snapshot = Mock(side_effect=[(True, [], 0), (True, [SquadRow(avatar, S.OUTBOUND)], 1)])
        flow.screenshot = Mock(return_value=np.zeros((1300, 720, 3), dtype=np.uint8))
        flow.click = Mock()
        flow.pause = Mock()
        flow.text_button = Mock(return_value=True)
        flow.panel = Mock(return_value=(1, [(unlocked, (100, 1100), avatar)] * 4))
        return flow

    def test_auto_deploy_is_clicked_once_then_dispatch(self):
        flow = self.make_dispatch()
        handle = flow.dispatch((300, 600), queue=1)
        self.assertEqual(1, handle.queue)
        self.assertEqual(S.OUTBOUND, handle.tracker.state)
        self.assertEqual(['进攻', '一键上阵', '出征'],
                         [call.args[0] for call in flow.text_button.call_args_list])

    def test_resume_panel_does_not_navigate_or_attack_again(self):
        flow = self.make_dispatch()
        avatar = flow.panel.return_value[1][0][2]
        flow.snapshot = Mock(return_value=(True, [SquadRow(avatar, S.OUTBOUND)], 1))
        handle = flow.dispatch_from_panel(queue=1)
        self.assertEqual(1, handle.queue)
        flow.pipeline.assert_not_called()
        self.assertEqual(['一键上阵', '出征'],
                         [call.args[0] for call in flow.text_button.call_args_list])

    def test_locked_queue_never_dispatches(self):
        flow = self.make_dispatch(unlocked=False)
        with self.assertRaisesRegex(RuntimeError, '未解锁'):
            flow.dispatch((300, 600), queue=1)
        self.assertEqual(['进攻'], [call.args[0] for call in flow.text_button.call_args_list])

    def test_unconfirmed_dispatch_is_not_replayed(self):
        flow = self.make_dispatch()
        flow.snapshot = Mock(return_value=(True, [], 0))
        with self.assertRaises(TimeoutError):
            flow.dispatch((300, 600), queue=1, timeout=.001)
        self.assertEqual(1, sum(call.args[0] == '出征' for call in flow.text_button.call_args_list))

    def test_stop_interrupts_wait(self):
        import threading
        flow = March.__new__(March)
        flow.engine = Mock(stop_event=threading.Event())
        flow.engine.stop_event.set()
        with self.assertRaises(InterruptedError):
            flow.pause(.5)


if __name__ == '__main__':
    unittest.main()
