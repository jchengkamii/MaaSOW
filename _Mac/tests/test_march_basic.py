"""基础行军检查：面板区分、队列选择、返回和防重复提交。"""
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import numpy as np
from agent.custom.action.march.march import March, MarchHandle, SquadRow
from agent.custom.action.march.state import MarchState as S, MarchTracker, parse_status
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

    def test_bubble_background_fallback_preserves_dispatch_guards(self):
        f=self.flow(March)
        hit=SimpleNamespace(box=SimpleNamespace(x=135,y=166,w=40,h=35))
        f.recognize=Mock(side_effect=[SimpleNamespace(hit=False,filtered_results=[]),
                                     SimpleNamespace(hit=True,filtered_results=[hit])])
        self.assertEqual([hit], f.templates(f.screenshot(), 'bubble', .65))
        params=f.recognize.call_args.args[2]
        self.assertTrue(params.green_mask)
        self.assertEqual(5, params.method)
        self.assertEqual([.85], params.threshold)
        f.ocr=Mock(return_value=[SimpleNamespace(text='出征')])
        f.templates=Mock(return_value=[hit])
        slots=[(False,(0,0),None)]*4
        f.panel_at_bubble=Mock(return_value=(1,slots,[False]*4))
        with self.assertRaisesRegex(RuntimeError,'队号校验通过 0'):
            f.panel(f.screenshot())
        f.click.assert_not_called()

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
        for text in ('L去X：598Y:380', '5去X:620Y：373', '5去X:620Y:373'):
            self.assertEqual(S.OUTBOUND, parse_status(text))
        for text in ('L去X：598', 'L00:01:30', '未知去X：598Y:380', '5去X:620', '55去X:620Y:373'):
            self.assertIsNone(parse_status(text))
        for kind,status in ((March,parse_status('L去X：598Y:380')),
                            (Pixiu,parse_status('5去X:620Y:373')),(LingEr,S.ASSEMBLING)):
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

        # Count OCR can fail while the known portrait and status remain clear.
        for kind,status in ((March,S.OUTBOUND),(Pixiu,S.OUTBOUND),(LingEr,S.ASSEMBLING)):
            f=self.flow(kind)
            a=np.random.default_rng(101).random((24,24,3))
            row=SquadRow(a,status)
            f.snapshot_rows_reliable=True
            f.snapshot=Mock(return_value=(False,[row],1))
            f.panel=Mock(return_value=(1,[(True,(0,0),a)]))
            f.panel_busy=[False];f.zero_disciples=Mock(return_value=False)
            f.text_button=Mock(return_value=True)
            handle=f._submit_from_panel(queue=1,existing=[])
            self.assertEqual(status,handle.tracker.state)
            self.assertEqual(3,f.snapshot.call_count)
            self.assertEqual(1,sum(c.args[0]=='出征' for c in f.text_button.call_args_list))
            with patch('agent.custom.action.march.march.similarity',return_value=.75):
                self.assertIsNone(f.matching_dispatch_row(False,[row],a))
            self.assertIsNone(f.matching_dispatch_row(False,[row,row],a))
            self.assertIsNone(f.matching_dispatch_row(False,[SquadRow(a,S.RETURNING)],a))
            f.snapshot_rows_reliable=False
            self.assertIsNone(f.matching_dispatch_row(False,[row],a))
            f.snapshot_rows_reliable=True
            f.pending_avatar=a;f.pending_rows=[];f.pending_baseline_reliable=True
            f.pending_dispatch=True;f.pending_handle=handle
            f.snapshot.reset_mock()
            self.assertTrue(f.reconcile_pending_dispatch())
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

        # Reproduce the logged 1/4 + missing icon transition. A known portrait
        # and readable status may recover the row; a replaced portrait may not.
        from maa.define import Rect
        f=self.flow(March)
        frame=np.random.default_rng(9).integers(0,256,(1300,720,3),dtype=np.uint8)
        f.screenshot.return_value=frame
        header=SimpleNamespace(box=Rect(56,60,48,30))
        anchor=SimpleNamespace(box=Rect(225,14,31,31))
        f.templates=Mock(return_value=[header])
        f.row_anchors=Mock(side_effect=[[anchor],[],[]])
        status=["集结中"]
        f.ocr=Mock(side_effect=lambda crop,expected=None,only_rec=False:
                   [SimpleNamespace(text=status[0] if only_rec else '1/4')])
        self.assertTrue(f.snapshot()[0])
        original_ocr = f.ocr
        f.ocr = Mock(side_effect=[[SimpleNamespace(text='门去X:620')],
                                 [SimpleNamespace(text='去X:620Y:373')]])
        row, texts = f.read_squad_row(frame, 0, anchor.box)
        self.assertEqual(S.OUTBOUND, row.status)
        self.assertEqual(2, f.ocr.call_count)
        f.ocr = original_ocr
        status[0]='战斗中'
        header.box=Rect(56,75,48,30)  # Header re-anchoring must not move a known row.
        valid,rows,count=f.snapshot()
        self.assertTrue(valid);self.assertEqual(S.FIGHTING,rows[0].status)
        self.assertEqual(1,count)
        f.screenshot.return_value=np.random.default_rng(10).integers(0,256,frame.shape,dtype=np.uint8)
        self.assertFalse(f.snapshot()[0])

    def test_rally_uses_level_controls_and_button_without_monster_name(self):
        f=LingEr.__new__(LingEr);f.engine=Mock();f.level=8
        f.screenshot=Mock(return_value=np.zeros((1326,720,3),dtype=np.uint8))
        icon=SimpleNamespace(box=SimpleNamespace(x=12,y=24,w=50,h=50))
        f.asset=Mock(return_value=[icon])
        f.ocr=Mock(return_value=[SimpleNamespace(text='8级')])
        self.assertEqual(8,f.search_level())
        self.assertEqual(['minus','plus'],[c.args[1] for c in f.asset.call_args_list])
        f.ocr.reset_mock()
        self.assertIsNotNone(f.target_dispatch_point(f.screenshot()))
        f.ocr.assert_not_called()
        f.asset.return_value=[]
        self.assertIsNone(f.target_dispatch_point(f.screenshot()))
        with self.assertRaisesRegex(RuntimeError,'加减按钮'):
            f.search_level()

        f.icon_button=Mock(return_value=True)
        f.region_text=Mock(side_effect=[False,False,True,True])
        f.adjust_level=Mock();f.pause=Mock()
        f.target_dispatch_point=Mock(return_value=(100,200))
        f.locate(None)
        f.icon_button.assert_called_once_with('search',(0,.70,.16,.84))
        f.pause.assert_called_once_with(.3)
        f.adjust_level.assert_called_once_with(8)


if __name__ == '__main__':
    unittest.main()
