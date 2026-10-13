"""基础行军检查：面板区分、队列选择、返回和防重复提交。"""
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import re
import numpy as np
from agent.custom.action.march.march import March, MarchHandle, SquadRow
from agent.custom.action.march.state import MarchState as S, MarchTracker
from agent.custom.action.auto_pixiu import Pixiu
from agent.custom.action.auto_ling_er import LingEr, RallyTracker


class MarchBasicTests(unittest.TestCase):
    def test_panel_failure_screenshot_is_saved(self):
        from PIL import Image
        image = np.zeros((2, 3, 3), dtype=np.uint8)
        image[:] = [10, 20, 30]
        flow = self.flow(March)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'agent/custom/action/march/dispatch_panel.py'
            with patch('agent.custom.action.march.dispatch_panel.__file__', str(source)):
                March.record_panel_failure(flow, image)
            with Image.open(root / 'debug/march_panel_failure.png') as saved:
                self.assertEqual((3, 2), saved.size)
                self.assertEqual((30, 20, 10), saved.getpixel((0, 0)))

    def flow(self, kind):
        f=kind.__new__(kind)
        f.engine=Mock(auto_stamina=False)
        f.tasker=Mock()
        f.screenshot=Mock(return_value=np.zeros((1326,720,3),dtype=np.uint8))
        f.pause=Mock();f.click=Mock();f.pipeline=Mock(return_value=False)
        f.record_panel_failure=Mock();f.target_dispatch_point=Mock(return_value=None)
        return f

    def test_transition_policy_is_shared_by_all_marches(self):
        for kind in (March,Pixiu,LingEr):
            with self.subTest(kind=kind):
                f=self.flow(kind)
                f.panel=Mock(side_effect=[RuntimeError('气泡未出现'),(1,[])])
                self.assertEqual((1,[]),f.ready_dispatch_panel())
                self.assertEqual(2,f.panel.call_count)
                f.click.assert_not_called();f.pipeline.assert_not_called()

    def test_panel_button_type_is_required_before_arrow_recognition(self):
        for kind in (March,Pixiu,LingEr):
            with self.subTest(kind=kind):
                f=self.flow(kind);f.ocr=Mock(return_value=[]);f.templates=Mock()
                with self.assertRaisesRegex(RuntimeError,'面板按钮'):
                    f.panel(f.screenshot())
                self.assertEqual([f'^{f.dispatch_caption}$'],f.ocr.call_args.args[1])
                f.templates.assert_not_called()

    def test_ambiguous_submit_recovers_existing_handle_without_replay(self):
        for kind,status in ((March,S.OUTBOUND),(Pixiu,S.OUTBOUND),(LingEr,S.ASSEMBLING)):
            with self.subTest(kind=kind):
                f=self.flow(kind)
                a=np.random.default_rng(98).random((24,24,3))
                f.allowed_queues=[1];f.ready_dispatch_panel=Mock(return_value=(1,[(True,(0,0),a)]))
                f.panel_busy=[False];f.pre_snapshot_reliable=True
                f.recover_world=Mock()
                f.snapshot=Mock(return_value=(True,[SquadRow(a,status)],1))
                def submit(*args,**kw):
                    f.pending_handle=MarchHandle(1,a,MarchTracker(),panel_avatar=a.copy())
                    f.pending_dispatch=True
                    raise TimeoutError('已提交但未确认')
                f._submit_from_panel=Mock(side_effect=submit)
                handle=f.dispatch_from_panel(queue=1,existing=[])
                self.assertEqual(status,handle.tracker.state)
                f._submit_from_panel.assert_called_once();f.recover_world.assert_called_once()
                self.assertEqual(3,f.snapshot.call_count)

    def test_only_selected_idle_queue_is_dispatched(self):
        f=self.flow(Pixiu)
        avatars=np.random.default_rng(42).random((4,24,24,3))
        f.allowed_queues=[1,4]
        f.panel_busy=[True,False,False,False]
        f.ready_dispatch_panel=Mock(return_value=(1,[(True,(0,0),a) for a in avatars]))
        f._submit_from_panel=Mock(return_value=MarchHandle(4,avatars[3],MarchTracker(state=S.OUTBOUND)))
        self.assertEqual(4,f.dispatch_from_panel(existing=[]).queue)
        f._submit_from_panel.assert_called_once_with(4,existing=[],timeout=15)

    def test_rally_completes_only_after_return_and_disappearance(self):
        tracker=RallyTracker()
        for status in (S.ASSEMBLING,S.OUTBOUND,S.RETURNING):
            self.assertFalse(tracker.observe(visible=True,status=status,reliable=True))
        missing=dict(visible=False,status=None,reliable=True,count_decreased=True)
        self.assertFalse(tracker.observe(**missing))
        self.assertFalse(tracker.observe(**missing))
        self.assertTrue(tracker.observe(**missing))
        self.assertEqual(S.COMPLETED,tracker.state)

    def test_rally_search_accepts_both_mutually_exclusive_bosses(self):
        for name in ('妖兽洞穴', '兽潮首领'):
            f=LingEr.__new__(LingEr)
            f.engine=Mock();f.level=8
            f.screenshot=Mock(return_value=np.zeros((1326,720,3),dtype=np.uint8))
            f.ocr=Mock(side_effect=[[SimpleNamespace(text=name)],[SimpleNamespace(text='8级')]])
            self.assertEqual(8,f.search_level())
            self.assertIsNotNone(re.fullmatch(f.target_title(),f'等级8 {name}'))
            other='兽潮首领' if name=='妖兽洞穴' else '妖兽洞穴'
            self.assertIsNone(re.fullmatch(f.target_title(),f'等级8 {other}'))
            f.ocr.side_effect=[[SimpleNamespace(text=other)]]
            with self.assertRaisesRegex(RuntimeError,'目标发生变化'):
                f.search_level()


if __name__ == '__main__':
    unittest.main()
