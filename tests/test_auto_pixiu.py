import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from agent.custom.action.auto_pixiu import NoFreeQueue, ZeroDisciples, RelocateAfterStamina, Pixiu, attack_count, run
from agent.custom.action.march.march import March, SquadRow
from agent.custom.action.run_configured_case import parse_attack_count, worker_command_with_options
from generate_interface import generate


class PixiuTests(unittest.TestCase):
    def test_recover_world_dismisses_panel_then_requires_two_clean_frames(self):
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock()
        flow.recovery_state = Mock(side_effect=['出征弹窗', '活动界面', '大世界默认态', '目标弹窗',
                                                '大世界默认态', '大世界默认态'])
        flow.screenshot = Mock(return_value=np.zeros((1300, 720, 3), dtype=np.uint8))
        flow.click = Mock()
        flow.pause = Mock()
        flow.pipeline = Mock(return_value=True)
        flow.recover_world()
        self.assertEqual(2, flow.click.call_count)
        self.assertEqual(6, flow.recovery_state.call_count)
        flow.pipeline.assert_called_once_with('通用行军进入大地图')

    def test_recovery_retries_same_attack_without_counting_failure(self):
        flow = Mock()
        flow.dispatch.side_effect = [RuntimeError('未识别'), 'handle']
        flow.reconcile_pending_dispatch.return_value = False
        with patch('agent.custom.action.auto_pixiu.Pixiu', return_value=flow):
            run(Mock(), SimpleNamespace(parameters={'attack_count': 1}))
        self.assertEqual(2, flow.dispatch.call_count)
        flow.recover_world.assert_called_once()

    def test_recovered_confirmed_dispatch_counts_without_reclick(self):
        flow = Mock()
        flow.dispatch.side_effect = TimeoutError('确认超时')
        flow.reconcile_pending_dispatch.return_value = True
        with patch('agent.custom.action.auto_pixiu.Pixiu', return_value=flow):
            run(Mock(), SimpleNamespace(parameters={'attack_count': 1}))
        flow.dispatch.assert_called_once()

    def test_recovery_is_bounded_and_user_stop_is_not_retried(self):
        for error, expected in [(RuntimeError('未识别'), 4), (InterruptedError('停止'), 1)]:
            with self.subTest(error=error):
                flow = Mock()
                flow.dispatch.side_effect = error
                flow.reconcile_pending_dispatch.return_value = False
                with patch('agent.custom.action.auto_pixiu.Pixiu', return_value=flow):
                    with self.assertRaises((RuntimeError, InterruptedError)):
                        run(Mock(), SimpleNamespace(parameters={'attack_count': 1}))
                self.assertEqual(expected, flow.dispatch.call_count)
                if isinstance(error, InterruptedError):
                    flow.recover_world.assert_not_called()

    def test_pending_dispatch_confirmed_from_unique_new_row(self):
        from agent.custom.action.march.state import MarchState
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock()
        flow.pause = Mock()
        flow.pending_dispatch = True
        a, b, c = np.random.default_rng(899).random((3, 24, 24, 3))
        flow.pending_avatar = a
        flow.pending_rows = [SquadRow(b, MarchState.RETURNING)]
        flow.pending_baseline_reliable = True
        flow.snapshot = Mock(return_value=(True, [SquadRow(c, MarchState.OUTBOUND)], 1))
        self.assertTrue(flow.reconcile_pending_dispatch())
        self.assertFalse(flow.pending_dispatch)
        self.assertEqual(3, flow.snapshot.call_count)

    def test_attack_waits_for_camera_to_settle_and_resets_on_missing_frame(self):
        flow = Pixiu.__new__(Pixiu)
        flow.screenshot = Mock(return_value=np.zeros((1300, 720, 3), dtype=np.uint8))
        flow.pixiu_attack_point = Mock(side_effect=[(360, 887), (360, 954), None,
                                                    (360, 954), (360, 953), (360, 954)])
        flow.pause = Mock()
        flow.click = Mock()
        self.assertTrue(flow.attack_pixiu(2))
        self.assertEqual(6, flow.pixiu_attack_point.call_count)
        flow.click.assert_called_once_with(360, 954)

    def test_missed_attack_retries_only_with_same_target_and_icon(self):
        flow = self.panel_recovery_flow()
        flow.panel = Mock(side_effect=[RuntimeError('气泡')] * 4 + [(2, [])])
        flow.pixiu_attack_point.return_value = (360, 954)
        flow.attack_pixiu = Mock(return_value=True)
        self.assertEqual((2, []), flow.ready_dispatch_panel())
        flow.attack_pixiu.assert_called_once_with(3)
        flow.pipeline.assert_not_called()

    def test_pixiu_attack_uses_icon_without_caption_ocr(self):
        flow = Pixiu.__new__(Pixiu)
        flow.screenshot = Mock(return_value=np.zeros((1300, 720, 3), dtype=np.uint8))
        flow.ocr = Mock(return_value=[SimpleNamespace(text='等级10藏宝灵貅',
            box=SimpleNamespace(x=100, y=130, w=250, h=30))])
        flow.templates = Mock(return_value=[SimpleNamespace(box=SimpleNamespace(x=210, y=460, w=80, h=80))])
        flow.click = Mock()
        flow.pause = Mock()
        self.assertTrue(flow.text_button('进攻', timeout=1))
        flow.click.assert_called_once_with(342.0, 985.0)
        self.assertEqual(['藏宝灵[貅貔]'], flow.ocr.call_args.args[1])

    def test_pixiu_attack_rejects_missing_target_and_ambiguous_icons(self):
        flow = Pixiu.__new__(Pixiu)
        image = np.zeros((1300, 720, 3), dtype=np.uint8)
        title = SimpleNamespace(box=SimpleNamespace(x=100, y=130, w=250, h=30))
        flow.templates = Mock()
        for titles in [[], [title, title]]:
            flow.ocr = Mock(return_value=titles)
            self.assertIsNone(flow.pixiu_attack_point(image))
        flow.templates.assert_not_called()
        flow.ocr.return_value = [title]
        for icons in [[], [Mock(), Mock()]]:
            flow.templates.return_value = icons
            self.assertIsNone(flow.pixiu_attack_point(image))
    def panel_recovery_flow(self):
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock(auto_stamina=True)
        flow.tasker = Mock()
        flow.screenshot = Mock()
        flow.pause = Mock()
        flow.pipeline = Mock(return_value=True)
        flow.click = Mock()
        flow.pixiu_attack_point = Mock(return_value=None)
        return flow

    def test_panel_transition_waits_without_clicking_again(self):
        flow = self.panel_recovery_flow()
        flow.panel = Mock(side_effect=[RuntimeError('气泡'), RuntimeError('气泡'), (2, [])])
        self.assertEqual((2, []), flow.ready_dispatch_panel())
        self.assertEqual(2, flow.pause.call_count)
        flow.pipeline.assert_not_called()
        flow.click.assert_not_called()

    def test_missing_initial_panel_checks_stamina_before_selecting(self):
        flow = self.panel_recovery_flow()
        flow.panel = Mock(side_effect=[RuntimeError('气泡')] * 4 + [(2, [])])
        self.assertEqual((2, []), flow.ready_dispatch_panel())
        flow.engine._try_auto_stamina.assert_called_once_with(flow.tasker)
        flow.click.assert_not_called()

    def test_missing_panel_without_stamina_prompt_stops(self):
        flow = self.panel_recovery_flow()
        flow.panel = Mock(side_effect=RuntimeError('气泡'))
        flow.pipeline.return_value = False
        with self.assertRaisesRegex(RuntimeError, '未发现体力不足提示'):
            flow.ready_dispatch_panel()
        flow.engine._try_auto_stamina.assert_not_called()

    def test_stamina_closed_panel_relocates_before_any_dispatch(self):
        flow = self.panel_recovery_flow()
        flow.panel = Mock(side_effect=RuntimeError('气泡'))
        with self.assertRaises(RelocateAfterStamina):
            flow.ready_dispatch_panel()
        flow.pipeline.assert_any_call('通用行军进入大地图')
        flow.click.assert_not_called()

    def test_stamina_relocation_does_not_count_attack_and_is_bounded(self):
        for failures in [1, 3]:
            with self.subTest(failures=failures):
                flow = Mock()
                flow.dispatch.side_effect = [RelocateAfterStamina()] * failures + ['handle']
                with patch('agent.custom.action.auto_pixiu.Pixiu', return_value=flow):
                    if failures == 3:
                        with self.assertRaisesRegex(RuntimeError, '反复无法'):
                            run(Mock(), SimpleNamespace(parameters={'attack_count': 1}))
                    else:
                        run(Mock(), SimpleNamespace(parameters={'attack_count': 1}))
                self.assertEqual(min(failures + 1, 3), flow.dispatch.call_count)

    def make_activity_entry(self, texts):
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock()
        flow.screenshot = Mock(return_value=np.zeros((1298, 720, 3), dtype=np.uint8))
        labels = [SimpleNamespace(text=text, box=SimpleNamespace(x=43, y=178, w=106, h=25))
                  for text in texts]
        def ocr(_image, patterns):
            import re
            return [label for label in labels if any(re.search(p, label.text) for p in patterns)]
        flow.ocr = Mock(side_effect=ocr)
        flow.recognize = Mock(return_value=SimpleNamespace(hit=True, filtered_results=[
            SimpleNamespace(box=SimpleNamespace(x=30, y=25, w=50, h=50))]))
        flow.click = Mock()
        flow.pause = Mock()
        flow.activity_visible = Mock(return_value=True)
        return flow

    def test_activity_entry_accepts_ocr_caption_with_extra_characters(self):
        for text in ['玩法活动', '[逍玩法活动]']:
            with self.subTest(text=text):
                flow = self.make_activity_entry([text])
                flow.open_activity()
                flow.click.assert_called_once_with(647.0, 267.0)
                flow.recognize.assert_called_once()

    def test_activity_entry_rejects_missing_or_ambiguous_caption(self):
        for texts in [['超值活动'], ['玩法活动', '[逍玩法活动]']]:
            with self.subTest(texts=texts):
                flow = self.make_activity_entry(texts)
                with self.assertRaisesRegex(RuntimeError, '未找到'):
                    flow.open_activity()
                flow.click.assert_not_called()

    def test_noisy_activity_caption_still_requires_matching_icon(self):
        flow = self.make_activity_entry(['[逍玩法活动]'])
        flow.recognize.return_value = SimpleNamespace(hit=False, filtered_results=[])
        with self.assertRaisesRegex(RuntimeError, '未唯一识别'):
            flow.open_activity()
        flow.click.assert_not_called()

    def test_quantity_ocr_fragments(self):
        def result(text, x, y, w, h):
            return SimpleNamespace(text=text, box=SimpleNamespace(x=x, y=y, w=w, h=h))

        cases = [
            ([result('141', 423, 198, 39, 15), result('/1047', 457, 197, 55, 18)], False),
            ([result('0', 440, 198, 12, 15), result('/', 452, 197, 8, 18), result('0', 460, 198, 12, 15)], True),
            ([result('141/1047', 423, 197, 89, 18)], False),
            ([result('0／1047', 423, 197, 89, 18)], True),
            # Separate rows or distant numbers must not become a fraction.
            ([result('141', 423, 180, 39, 15), result('/1047', 457, 208, 55, 18)], None),
            ([result('141', 370, 198, 39, 15), result('/1047', 490, 197, 55, 18)], None),
            ([result('141', 423, 198, 39, 15)], None),
        ]
        for fragments, expected in cases:
            with self.subTest(fragments=[item.text for item in fragments], expected=expected):
                flow = Pixiu.__new__(Pixiu)
                flow.screenshot = Mock(return_value=np.zeros((1300, 720, 3), dtype=np.uint8))
                flow.ocr = Mock(return_value=[result('弟子数量', 415, 146, 90, 25),
                                             result('444000', 280, 280, 90, 20), *fragments])
                if expected is None:
                    with self.assertRaises(RuntimeError):
                        flow.zero_disciples()
                else:
                    self.assertEqual(expected, flow.zero_disciples())

    def test_unreadable_hud_continues_to_target_and_panel(self):
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock()
        flow.pipeline = Mock(return_value=True)
        flow.snapshot = Mock(return_value=(False, [], 0))
        flow.pause = Mock()
        flow.text_button = Mock(return_value=True)
        flow.dispatch_from_panel = Mock(return_value='handle')
        locate = Mock()
        self.assertEqual('handle', flow.dispatch(None, select_target=locate))
        self.assertEqual(3, flow.snapshot.call_count)
        locate.assert_called_once_with(flow.engine)
        flow.dispatch_from_panel.assert_called_once_with(queue=None, existing=[], timeout=15)

    def test_hud_retry_recovers_rows(self):
        flow = Pixiu.__new__(Pixiu)
        rows = [Mock()]
        flow.snapshot = Mock(side_effect=[(False, [], 0), (True, rows, 1)])
        flow.pause = Mock()
        self.assertIs(rows, flow.pre_dispatch_rows())
        flow.pause.assert_called_once_with(.3)

    def test_busy_icon_excludes_first_squad_without_portrait_match(self):
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock()
        flow.screenshot = Mock()
        slots = [(True, (0, 0), a) for a in np.random.default_rng(82).random((4,24,24,3))]
        flow.panel = Mock(return_value=(1, slots))
        flow.panel_busy = [True, False, False, False]
        with patch.object(March, 'dispatch_from_panel', return_value='handle') as dispatch:
            flow.dispatch_from_panel(existing=[])
        self.assertEqual(2, dispatch.call_args.args[0])
        self.assertEqual(4, flow.queue_capacity)
        self.assertEqual(1, flow.occupied_before_dispatch)


    def test_first_free_squad_wins_over_selected_second(self):
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock()
        flow.screenshot = Mock()
        slots = [(True, (0, 0), a) for a in np.random.default_rng(71).random((4,24,24,3))]
        flow.panel = Mock(return_value=(2, slots))
        with patch.object(March, 'dispatch_from_panel', return_value='handle') as dispatch:
            flow.dispatch_from_panel()
        self.assertEqual(1, dispatch.call_args.args[0])

    def test_first_squad_uncertain_frame_is_rechecked(self):
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock()
        flow.screenshot = Mock()
        flow.pause = Mock()
        slots = [(True, (0, 0), a) for a in np.random.default_rng(72).random((4,24,24,3))]
        uncertain = [(False, slots[0][1], slots[0][2])] + slots[1:]
        flow.panel = Mock(side_effect=[(2, uncertain), (2, slots)])
        with patch.object(March, 'dispatch_from_panel', return_value='handle') as dispatch:
            flow.dispatch_from_panel()
        self.assertEqual(1, dispatch.call_args.args[0])
        flow.pause.assert_called_once_with(.35)

    def test_zero_disciples_never_clicks_dispatch(self):
        flow = Pixiu.__new__(Pixiu)
        flow.zero_disciples = Mock(return_value=True)
        with patch.object(March, 'text_button') as button:
            with self.assertRaises(ZeroDisciples):
                flow.text_button('出征')
            button.assert_not_called()

    def test_zero_disciples_retry_does_not_count_attack(self):
        flow = Mock()
        flow.dispatch.side_effect = [ZeroDisciples(), 'handle']
        flow.occupied_before_dispatch = 2
        with patch('agent.custom.action.auto_pixiu.Pixiu', return_value=flow):
            run(Mock(), SimpleNamespace(parameters={'attack_count': 1}))
        self.assertEqual(2, flow.dispatch.call_count)
        flow.close_and_wait_for_return.assert_called_once()
        self.assertEqual(2, flow.close_and_wait_for_return.call_args.args[0])

    def test_zero_disciples_waits_for_actual_return_despite_free_slots(self):
        import time
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock()
        flow.screenshot = Mock(return_value=np.zeros((1300, 720, 3), dtype=np.uint8))
        flow.click = Mock()
        flow.pause = Mock()
        flow.pipeline = Mock(return_value=True)
        flow.snapshot = Mock(side_effect=[(True, [], 2), (False, [], 0),
                                          (True, [], 1), (True, [], 2),
                                          (True, [], 1), (True, [], 1)])
        flow.close_and_wait_for_return(2, time.monotonic() + 5)
        self.assertEqual(6, flow.snapshot.call_count)
        flow.click.assert_called_once_with(720 * .12, 1300 * .20)

    def test_native_entry_screenshots_without_controller(self):
        import subprocess
        import sys
        from pathlib import Path
        result = subprocess.run([sys.executable, '-X', 'utf8',
                                 str(Path(__file__).with_name('pixiu_entry_native_probe.py'))],
                                capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_count_validation_and_parameter_bridge(self):
        for invalid in (0, -1, True, 1.2, '3.5', 10001, None):
            with self.assertRaises(ValueError):
                attack_count(invalid)
        self.assertEqual(10000, attack_count('10000'))
        self.assertEqual(3, parse_attack_count('{"case_id":"auto_pixiu","attack_count":3}'))
        with self.assertRaises(ValueError):
            parse_attack_count('{"case_id":"auto_radar","attack_count":3}')
        self.assertEqual(['--attack-count', '3'], worker_command_with_options('auto_pixiu', True, attack_count=3)[-2:])
        options = generate()['option']
        self.assertEqual('1', options['貔貅进攻次数']['inputs'][0]['default'])

    def test_full_unknown_and_free_queues(self):
        flow = Pixiu.__new__(Pixiu)
        flow.screenshot = Mock(return_value=np.zeros((1300, 720, 3), dtype=np.uint8))
        flow.queue_capacity = 4
        flow.snapshot = Mock(return_value=(False, [], 0))
        flow.ocr = Mock(return_value=[SimpleNamespace(text='4/4')])
        self.assertFalse(flow.free_queue())
        flow.ocr.return_value = []
        self.assertIsNone(flow.free_queue())
        flow.ocr.return_value = [SimpleNamespace(text='2/4')]
        self.assertTrue(flow.free_queue())
        flow.ocr.return_value = [SimpleNamespace(text='1/4')]
        self.assertTrue(flow.free_queue())
        flow.snapshot.assert_called_once_with()

    def test_wait_for_positive_hud_after_all_squads_busy(self):
        flow = Mock()
        flow.dispatch.side_effect = [NoFreeQueue(), 'handle']
        flow.free_queue.side_effect = [False, None, False, None, True]
        with patch('agent.custom.action.auto_pixiu.Pixiu', return_value=flow):
            run(Mock(), SimpleNamespace(parameters={'attack_count': 1}))
        self.assertEqual(2, flow.dispatch.call_count)
        self.assertEqual(5, flow.pause.call_count)
        flow.close_dispatch_panel.assert_called_once_with()
        calls = [call[0] for call in flow.mock_calls]
        first, second = [i for i, name in enumerate(calls) if name == 'dispatch']
        self.assertEqual(5, calls[first + 1:second].count('free_queue'))

    def test_snapshot_fallback_uses_all_occupied_counts(self):
        flow = Pixiu.__new__(Pixiu)
        flow.screenshot = Mock(return_value=np.zeros((1300, 720, 3), dtype=np.uint8))
        flow.queue_capacity = 4
        flow.ocr = Mock(return_value=[])
        for occupied in range(5):
            with self.subTest(occupied=occupied):
                flow.snapshot = Mock(return_value=(True, [], occupied))
                self.assertEqual(occupied < 4, flow.free_queue())
        flow.snapshot.return_value = (False, [], 1)
        self.assertIsNone(flow.free_queue())

    def test_fallback_one_of_four_continues_dispatch_without_waiting(self):
        flow = Mock()
        real_flow = Pixiu.__new__(Pixiu)
        real_flow.screenshot = Mock(return_value=np.zeros((1300, 720, 3), dtype=np.uint8))
        real_flow.queue_capacity = 4
        real_flow.ocr = Mock(return_value=[])
        real_flow.snapshot = Mock(return_value=(True, [], 1))
        flow.free_queue.side_effect = real_flow.free_queue
        with patch('agent.custom.action.auto_pixiu.Pixiu', return_value=flow):
            run(Mock(), SimpleNamespace(parameters={'attack_count': 2}))
        self.assertEqual(2, flow.dispatch.call_count)
        flow.pause.assert_not_called()

    def test_all_squads_returned_and_hud_disappeared(self):
        flow = Pixiu.__new__(Pixiu)
        flow.screenshot = Mock(return_value=np.zeros((1300, 720, 3), dtype=np.uint8))
        flow.ocr = Mock(return_value=[])
        flow.snapshot = Mock(return_value=(True, [], 0))
        self.assertTrue(flow.free_queue())
        flow.snapshot.return_value = (False, [], 0)
        self.assertIsNone(flow.free_queue())

    def test_wait_then_dispatch_exact_requested_times(self):
        engine = Mock()
        flow = Mock()
        flow.free_queue.side_effect = [False, False, True]
        with patch('agent.custom.action.auto_pixiu.Pixiu', return_value=flow):
            run(engine, SimpleNamespace(parameters={'attack_count': 2}))
        self.assertEqual(2, flow.dispatch.call_count)
        self.assertEqual(2, flow.pause.call_count)

    def test_first_dispatch_does_not_wait_for_hud(self):
        flow = Mock()
        flow.free_queue.side_effect = AssertionError('first attempt must inspect dispatch panel')
        with patch('agent.custom.action.auto_pixiu.Pixiu', return_value=flow):
            run(Mock(), SimpleNamespace(parameters={'attack_count': 1}))
        flow.dispatch.assert_called_once()
        flow.pause.assert_not_called()

    def test_four_queues_one_busy_selects_another(self):
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock()
        avatars = np.random.default_rng(23).random((4, 24, 24, 3))
        flow.screenshot = Mock()
        flow.panel = Mock(return_value=(1, [(True, (0, 0), a) for a in avatars]))
        existing = [SquadRow(avatars[0], None)]
        with patch.object(March, 'dispatch_from_panel', return_value='handle') as dispatch:
            self.assertEqual('handle', flow.dispatch_from_panel(existing=existing))
        self.assertEqual(4, flow.queue_capacity)
        self.assertEqual(2, dispatch.call_args.args[0])

    def test_no_free_panel_waits_then_retries_without_counting(self):
        flow = Mock()
        flow.dispatch.side_effect = [NoFreeQueue(), 'handle']
        flow.free_queue.return_value = True
        with patch('agent.custom.action.auto_pixiu.Pixiu', return_value=flow):
            run(Mock(), SimpleNamespace(parameters={'attack_count': 1}))
        self.assertEqual(2, flow.dispatch.call_count)
        flow.pause.assert_called_once_with(1)
        flow.close_dispatch_panel.assert_called_once_with()

    def test_returned_first_squad_replaces_stale_hud_occupancy(self):
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock()
        flow.screenshot = Mock()
        flow.pause = Mock()
        avatars = np.random.default_rng(123).random((4, 24, 24, 3))
        slots = [(True, (0, 0), avatar) for avatar in avatars]
        flow.panel = Mock(return_value=(1, slots))
        flow.panel_busy = [False, True, True, True]
        existing = [SquadRow(avatar, None) for avatar in avatars]
        with patch.object(March, 'dispatch_from_panel', return_value='handle') as dispatch:
            self.assertEqual('handle', flow.dispatch_from_panel(existing=existing))
        self.assertEqual(1, dispatch.call_args.args[0])
        self.assertEqual([id(row) for row in existing[1:]],
                         [id(row) for row in dispatch.call_args.kwargs['existing']])
        self.assertEqual(3, flow.occupied_before_dispatch)
        self.assertEqual(4, len(existing))
        self.assertEqual(2, flow.panel.call_count)

    def test_returned_squad_must_remain_free_on_second_frame(self):
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock()
        flow.screenshot = Mock()
        flow.pause = Mock()
        avatars = np.random.default_rng(124).random((4, 24, 24, 3))
        slots = [(True, (0, 0), avatar) for avatar in avatars]
        states = iter([[False, True, True, True], [True, True, True, True]])
        def panel(_image):
            flow.panel_busy = next(states)
            return 1, slots
        flow.panel = Mock(side_effect=panel)
        with patch.object(March, 'dispatch_from_panel') as dispatch:
            with self.assertRaises(NoFreeQueue):
                flow.dispatch_from_panel(existing=[SquadRow(a, None) for a in avatars])
        dispatch.assert_not_called()

    def test_close_panel_clicks_blank_before_entering_world(self):
        flow = Pixiu.__new__(Pixiu)
        flow.screenshot = Mock(return_value=np.zeros((1300, 720, 3), dtype=np.uint8))
        calls = Mock()
        flow.click = calls.click
        flow.pause = calls.pause
        flow.pipeline = calls.pipeline
        flow.pipeline.return_value = True
        flow.close_dispatch_panel()
        self.assertEqual(['click', 'pause', 'pipeline'], [call[0] for call in calls.mock_calls])
        flow.click.assert_called_once_with(86.39999999999999, 260.0)

    def test_unconfirmed_dispatch_stops_without_retry(self):
        flow = Mock()
        flow.free_queue.return_value = True
        flow.dispatch.side_effect = TimeoutError('unconfirmed')
        flow.reconcile_pending_dispatch.side_effect = TimeoutError('still unconfirmed')
        with patch('agent.custom.action.auto_pixiu.Pixiu', return_value=flow):
            with self.assertRaises(TimeoutError):
                run(Mock(), SimpleNamespace(parameters={'attack_count': 2}))
        flow.dispatch.assert_called_once()

    def test_tab_search_switches_direction_and_checks_target(self):
        flow = Pixiu.__new__(Pixiu)
        flow.open_activity = Mock()
        flow.engine = Mock()
        flow.activity_visible = Mock(return_value=True)
        flow.tab_signature = Mock(side_effect=[[('群仙除崇', 50)], [('活动日历', 50)]])
        flow.region_text = Mock(side_effect=[False, True, False, True, True, True, True])
        flow.swipe_tabs = Mock()
        flow.locate(None)
        self.assertEqual([False, True], [call.kwargs['left'] for call in flow.swipe_tabs.call_args_list])
        patterns = [call.args[0] for call in flow.region_text.call_args_list]
        self.assertEqual(['^活动日历$', '^活动日历$', '^祥瑞聚宝$', '^祥瑞聚宝$'], patterns[:4])
        self.assertEqual('藏宝灵[貅貔]', flow.region_text.call_args.args[0])

    def test_stops_after_two_unchanged_swipes(self):
        for toward_start in (True, False):
            flow = Pixiu.__new__(Pixiu)
            flow.activity_visible = Mock(return_value=True)
            flow.region_text = Mock(return_value=False)
            flow.tab_signature = Mock(return_value=[('锁妖试炼', 50)])
            flow.swipe_tabs = Mock()
            with self.assertRaisesRegex(RuntimeError, '边界或滑动未生效'):
                flow.find_activity_tab('活动日历' if toward_start else '祥瑞聚宝', toward_start=toward_start)
            self.assertEqual(2, flow.swipe_tabs.call_count)

    def test_calendar_visible_needs_no_reset_swipe(self):
        flow = Pixiu.__new__(Pixiu)
        flow.activity_visible = Mock(return_value=True)
        flow.region_text = Mock(return_value=True)
        flow.swipe_tabs = Mock()
        flow.find_activity_tab('活动日历', toward_start=True)
        flow.swipe_tabs.assert_not_called()
        self.assertFalse(flow.region_text.call_args.kwargs['click'])

    def test_failed_entry_never_swipes(self):
        flow = Pixiu.__new__(Pixiu)
        flow.open_activity = Mock(side_effect=RuntimeError('未打开'))
        flow.swipe_tabs = Mock()
        with self.assertRaises(RuntimeError):
            flow.locate(None)
        flow.swipe_tabs.assert_not_called()

    def test_lost_activity_page_never_swipes(self):
        flow = Pixiu.__new__(Pixiu)
        flow.activity_visible = Mock(return_value=False)
        flow.controller = Mock()
        with self.assertRaisesRegex(RuntimeError, '停止滑动'):
            flow.swipe_tabs(True)
        flow.controller.post_swipe.assert_not_called()

    def test_stamina_retry_requires_positive_prompt_and_toggle(self):
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock(auto_stamina=True)
        flow.tasker = Mock()
        flow.screenshot = Mock()
        flow.panel = Mock(return_value=(1, [(True, (0, 0), np.zeros((24, 24, 3)))]))
        flow.pipeline = Mock(return_value=False)
        with patch.object(March, 'dispatch_from_panel', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                flow.dispatch_from_panel()
        flow.engine._try_auto_stamina.assert_not_called()
        flow.pipeline.return_value = True
        flow.engine.auto_stamina = False
        with patch.object(March, 'dispatch_from_panel', side_effect=TimeoutError):
            with self.assertRaisesRegex(RuntimeError, '未勾选'):
                flow.dispatch_from_panel()
        flow.engine.auto_stamina = True
        with patch.object(March, 'dispatch_from_panel', side_effect=[TimeoutError(), 'handle']) as dispatch:
            self.assertEqual('handle', flow.dispatch_from_panel())
            self.assertEqual(2, dispatch.call_count)


if __name__ == '__main__':
    unittest.main()
