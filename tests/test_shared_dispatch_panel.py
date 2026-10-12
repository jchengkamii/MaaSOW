from __future__ import annotations
import unittest
from unittest.mock import Mock
from types import SimpleNamespace
import numpy as np
from agent.custom.action.march.march import March, MarchHandle, SquadRow
from agent.custom.action.march.dispatch_panel import DispatchPanel
from agent.custom.action.march.state import MarchState as S, MarchTracker
from agent.custom.action.auto_pixiu import Pixiu
from agent.custom.action.auto_ling_er import LingEr, RallyTracker


class SharedPanelTests(unittest.TestCase):
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

    def test_only_verified_target_allows_one_entry_retry(self):
        for kind in (Pixiu,LingEr):
            with self.subTest(kind=kind):
                f=self.flow(kind)
                f.panel=Mock(side_effect=[RuntimeError('气泡')] * 4 + [(1,[])])
                f.target_dispatch_point.return_value=(100,200)
                f.open_target_panel=Mock(return_value=True)
                self.assertEqual((1,[]),f.ready_dispatch_panel())
                f.open_target_panel.assert_called_once_with(3)
                f.pipeline.assert_not_called()

    def test_missing_target_never_reclicks_entry_or_submits(self):
        for kind in (March,Pixiu,LingEr):
            with self.subTest(kind=kind):
                f=self.flow(kind);f.panel=Mock(side_effect=RuntimeError('气泡'))
                f.open_target_panel=Mock();f._submit_from_panel=Mock()
                with self.assertRaisesRegex(RuntimeError,'未发现体力不足'):
                    f.ready_dispatch_panel()
                f.open_target_panel.assert_not_called();f._submit_from_panel.assert_not_called()
                f.record_panel_failure.assert_called_once()

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

    def test_return_inspection_failure_recovers_without_count_or_submit(self):
        f=self.flow(LingEr)
        a=np.random.default_rng(99).random((24,24,3))
        f.return_panel_open=True;f.return_panel_rows=[]
        f.ready_dispatch_panel=Mock(side_effect=RuntimeError('气泡未确认'))
        f.recover_world=Mock();f.close_dispatch_panel=Mock();f._submit_from_panel=Mock()
        h=MarchHandle(1,a,RallyTracker(assembled=True,departed=True,missing_after_departure=3),panel_avatar=a)
        self.assertFalse(f.confirm_returned_in_panel(h,keep_open=True))
        self.assertNotEqual(S.COMPLETED,h.tracker.state)
        f.recover_world.assert_called_once();f.close_dispatch_panel.assert_not_called()
        f._submit_from_panel.assert_not_called()
        self.assertFalse(f.return_panel_open)

    def test_submit_state_rules_do_not_accept_other_panel_lifecycle(self):
        for kind,wrong in ((March,S.ASSEMBLING),(Pixiu,S.ASSEMBLING),(LingEr,S.OUTBOUND)):
            self.assertNotIn(wrong,kind.dispatch_states)

if __name__ == '__main__':unittest.main()
