import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from agent.custom.action.auto_pixiu import Pixiu, NoFreeQueue, attack_queues, run
from agent.custom.action.march.march import March
from agent.custom.action.run_configured_case import selected_attack_queues, worker_command_with_options
from generate_interface import generate


class PixiuQueueTests(unittest.TestCase):
    def test_every_checkbox_combination_and_invalid_selection(self):
        data = generate()
        task = next(t for t in data['task'] if t['name'] == 'auto_pixiu')
        option = data['option']['貔貅出征队列']
        self.assertIn('貔貅出征队列', task['option'])
        self.assertEqual(['1', '2', '3', '4'], option['default_case'])
        for bits in range(16):
            nodes = dict(task['pipeline_override'])
            selected = [q for q in range(1, 5) if bits & (1 << (q - 1))]
            for q in selected:
                nodes.update(option['cases'][q - 1]['pipeline_override'])
            context = Mock()
            context.get_node_data.side_effect = nodes.get
            if selected:
                self.assertEqual(selected, selected_attack_queues(context))
            else:
                with self.assertRaises(ValueError):
                    selected_attack_queues(context)
        for bad in ([], [True], [0], [5], [1, 1], '', '1,5', None):
            with self.assertRaises(ValueError):
                attack_queues(bad)

    def test_worker_and_run_receive_selection(self):
        from agent.worker import execute
        self.assertEqual(['--attack-queues', '2,4'],
                         worker_command_with_options('auto_pixiu', True, attack_queues=[2, 4])[-2:])
        with patch('agent.worker.AutomationEngine') as engine, patch('agent.worker.AutomationMutex'), patch('agent.worker._emit_result'):
            engine.return_value.execute_case.return_value = SimpleNamespace(status='passed', message='ok', elapsed=0)
            self.assertEqual(0, execute('auto_pixiu', attack_queues='2,4'))
            case = engine.return_value.execute_case.call_args.args[0]
            self.assertEqual([2, 4], case.parameters['attack_queues'])
            with patch('agent.custom.action.auto_pixiu.Pixiu') as flow:
                run(Mock(), case)
                self.assertEqual([2, 4], flow.return_value.allowed_queues)
            engine.reset_mock()
            self.assertEqual(1, execute('auto_ling_er', attack_queues='2,4'))
            engine.assert_not_called()

    def make_flow(self):
        flow = Pixiu.__new__(Pixiu)
        flow.engine = Mock()
        flow.allowed_queues = [2, 4]
        avatars = np.random.default_rng(755).random((4, 24, 24, 3))
        slots = [(True, (0, 0), a) for a in avatars]
        flow.ready_dispatch_panel = Mock(return_value=(1, slots))
        flow.panel_busy = [False, True, False, False]
        return flow, avatars

    def test_skips_unselected_free_squads_and_uses_fourth(self):
        flow, _ = self.make_flow()
        with patch.object(March, 'dispatch_from_panel', return_value='handle') as dispatch:
            self.assertEqual('handle', flow.dispatch_from_panel())
            self.assertEqual(4, dispatch.call_args.args[0])

    def test_all_selected_busy_does_not_dispatch_unselected(self):
        flow, _ = self.make_flow()
        flow.panel_busy = [False, True, False, True]
        with patch.object(March, 'dispatch_from_panel') as dispatch:
            with self.assertRaises(NoFreeQueue):
                flow.dispatch_from_panel()
            dispatch.assert_not_called()

    def test_waits_for_selected_return_with_two_reliable_frames(self):
        flow, avatars = self.make_flow()
        flow.allowed_avatars = {2: avatars[1], 4: avatars[3]}
        rows = [SimpleNamespace(avatar=avatars[q - 1]) for q in (2, 4)]
        flow.snapshot = Mock(return_value=(True, rows, 2))
        self.assertFalse(flow.free_queue())  # Other two squads idle is insufficient.
        flow.snapshot.return_value = (True, rows[1:], 1)
        self.assertFalse(flow.free_queue())
        flow.snapshot.return_value = (False, [], 0)
        self.assertIsNone(flow.free_queue())
        flow.snapshot.return_value = (True, rows[1:], 1)
        self.assertFalse(flow.free_queue())
        self.assertTrue(flow.free_queue())

    def test_incomplete_rows_cannot_prove_selected_return(self):
        flow, avatars = self.make_flow()
        flow.allowed_avatars = {2: avatars[1]}
        flow.snapshot = Mock(return_value=(True, [], 1))
        self.assertIsNone(flow.free_queue())
        with self.assertRaises(ValueError):
            flow.dispatch_from_panel(queue=1)


if __name__ == '__main__':
    unittest.main()
