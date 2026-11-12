"""基础行军检查：面板区分、队列选择、返回和防重复提交。"""
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import numpy as np
from agent.custom.action.march.march import March, MarchHandle, SquadRow
from agent.custom.action.march.state import MarchState as S, MarchTracker, parse_status
from agent.custom.action.auto_pixiu import Pixiu, run as run_pixiu
from agent.custom.action.auto_ling_er import LingEr, RallyTracker, run as run_ling_er
from agent.custom.action.auto_fu_hu import FuHu, FuHuFinished, run as run_fu_hu


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
            with patch('agent.custom.action.march.dispatch_panel.__file__', str(source)):
                March.record_panel_failure(flow,image,stage='row_recovery')
            self.assertTrue((root/'debug/march_row_recovery_failure.png').is_file())

    def flow(self, kind):
        f=kind.__new__(kind)
        f.engine=Mock(auto_stamina=False)
        f.tasker=Mock()
        f.screenshot=Mock(return_value=np.zeros((1326,720,3),dtype=np.uint8))
        f.pause=Mock();f.click=Mock();f.pipeline=Mock(return_value=False)
        f.record_panel_failure=Mock();f.target_dispatch_point=Mock(return_value=None)
        if kind is FuHu:
            f.check_icon_completion=Mock()
        return f

    def test_pixiu_searches_left_right_left_then_returns_to_world(self):
        import json
        from agent.core import PROJECT_DIR
        nodes=json.loads((PROJECT_DIR/'resource/base/pipeline/Common/March.json').read_text(encoding='utf-8'))
        self.assertIn('通用行军蓝色返回',nodes['通用行军进入大地图']['next'])
        back=nodes['通用行军蓝色返回']
        self.assertIn('AutoPixiu/activity_back.png',back['template'])
        self.assertEqual('Click',back['action'])
        self.assertEqual([0,-180,160,180],back['roi'])
        for found_on in (1,2,3,None):
            with self.subTest(found_on=found_on):
                f=self.flow(Pixiu)
                f.open_activity=Mock();f.activity_visible=Mock(return_value=True)
                f.pipeline.return_value=True
                position=1
                directions=[]
                def swipe(x0,y0,x1,y1,duration):
                    nonlocal position
                    direction='左' if x1 < x0 else '右'
                    if not directions or directions[-1] != direction:
                        directions.append(direction)
                    position=max(0,min(2,position+(1 if direction == '左' else -1)))
                    return SimpleNamespace(wait=lambda:SimpleNamespace(succeeded=True))
                f.controller=Mock()
                f.controller.post_swipe.side_effect=swipe
                f.tab_signature=Mock(side_effect=lambda:[('其他活动',position*40)])
                def text(pattern,region,click=False):
                    if region == (.15,.88,1,1):
                        self.assertEqual('^祥瑞聚宝$',pattern)
                        self.assertTrue(click)
                        return found_on == len(directions)
                    return True
                f.region_text=Mock(side_effect=text)
                if found_on is None:
                    with self.assertRaisesRegex(RuntimeError,'已返回大地图'):
                        f.locate(None)
                    f.pipeline.assert_called_once_with('通用行军进入大地图')
                    self.assertTrue(all(c.args[1] == (.15,.88,1,1) for c in f.region_text.call_args_list))
                else:
                    f.locate(None)
                    f.pipeline.assert_not_called()
                    self.assertTrue(any(c.args[0] == '^搜索灵[貅貔]$' for c in f.region_text.call_args_list))
                self.assertEqual(['左','右','左'][:found_on],directions)
                self.assertLessEqual(f.controller.post_swipe.call_count,11)

    def test_pixiu_retries_recovered_lookup_without_waiting_for_hud(self):
        f=self.flow(Pixiu)
        f.pipeline.return_value=True
        f.free_queue=Mock(side_effect=[False,True,None])
        f.dispatch=Mock(side_effect=[object(),RuntimeError('已返回大地图'),object()])
        f.recover_world=Mock();f.pending_dispatch=False
        case=SimpleNamespace(parameters={'attack_count':2,'attack_queues':[2,3,4]})
        with patch('agent.custom.action.auto_pixiu.Pixiu',return_value=f):
            self.assertIn('已完成 2 次',run_pixiu(f.engine,case))
        self.assertEqual(3,f.dispatch.call_count)
        self.assertEqual(2,f.free_queue.call_count)
        f.recover_world.assert_called_once()

    def test_pixiu_pending_dispatch_waits_for_same_squad_idle_before_retry(self):
        a,b=np.random.default_rng(112).random((2,24,24,3))
        handle=MarchHandle(4,a,MarchTracker(),panel_avatar=a.copy())
        f=self.flow(Pixiu)
        f.pending_handle=handle;f.pending_dispatch=True
        f.recover_world=Mock();f.locate=Mock();f.open_target_panel=Mock(return_value=True)
        f.dispatch=Mock();f.text_button=Mock()
        f.reconcile_pending_dispatch=Mock(side_effect=[RuntimeError('出征未确认')]*3)
        # A busy badge on the second frame or a changed portrait must keep
        # the dispatch pending. Only two idle frames of the original squad retry.
        reads=iter([(False,a),(True,a),(False,b),(False,a),(False,a)])
        def panel():
            self.assertTrue(f.pending_dispatch)
            busy,avatar=next(reads)
            f.panel_busy=[False,False,False,busy]
            return 4,[(True,(0,0),b)]*3+[(True,(0,0),avatar)]
        f.ready_dispatch_panel=Mock(side_effect=panel)
        with patch('agent.custom.action.auto_pixiu.time.monotonic',return_value=0):
            self.assertFalse(f.recover_dispatch(900))
        self.assertFalse(f.pending_dispatch)
        self.assertEqual(3,f.reconcile_pending_dispatch.call_count)
        self.assertEqual(5,f.ready_dispatch_panel.call_count)
        f.dispatch.assert_not_called();f.text_button.assert_not_called()
        f.pending_dispatch=True
        f.reconcile_pending_dispatch.side_effect=None
        f.reconcile_pending_dispatch.return_value=True
        f.ready_dispatch_panel.reset_mock()
        with patch('agent.custom.action.auto_pixiu.time.monotonic',return_value=0):
            self.assertTrue(f.recover_dispatch(900))
        f.ready_dispatch_panel.assert_not_called()
        with patch('agent.custom.action.auto_pixiu.time.monotonic',return_value=900):
            with self.assertRaisesRegex(TimeoutError,'等待重试超时'):
                f.recover_dispatch(900)
        self.assertTrue(f.pending_dispatch)
        f.dispatch.assert_not_called();f.text_button.assert_not_called()

    def test_confirmed_hud_portraits_prevent_false_idle_and_dispatch_timeouts(self):
        f=self.flow(Pixiu)
        panel_avatar,hud_avatar,changed=np.random.default_rng(113).random((3,24,24,3))
        row=SquadRow(hud_avatar,S.OUTBOUND)
        slots=[(False,(0,0),changed)]*2+[(True,(0,0),panel_avatar)]
        f.panel=Mock(return_value=(3,slots));f.panel_busy=[False]*3
        f.zero_disciples=Mock(return_value=False);f.text_button=Mock(return_value=True)
        f.snapshot=Mock(return_value=(True,[row],1))
        # Different panel/HUD art is learned only after unique added-squad
        # evidence has confirmed the initial dispatch for three frames.
        handle=f._submit_from_panel(queue=3,existing=[])
        self.assertEqual(3,f.snapshot.call_count)
        np.testing.assert_array_equal(hud_avatar,f.hud_avatar(3,panel_avatar))
        f.allowed_queues=[3];f.allowed_avatars={3:panel_avatar}
        self.assertFalse(f.free_queue());self.assertFalse(f.free_queue())
        f.snapshot.return_value=(False,[row],1)
        self.assertIsNone(f.free_queue())
        # A later dispatch can be reconciled even if the old pre-activity
        # baseline is unavailable, using the previously confirmed HUD portrait.
        f.pending_dispatch=True;f.pending_handle=handle;f.pending_avatar=panel_avatar
        f.pending_baseline_reliable=False;f.pending_rows=[]
        f.snapshot.return_value=(True,[row],1);f.snapshot.reset_mock()
        f.text_button.reset_mock()
        self.assertTrue(f.reconcile_pending_dispatch())
        self.assertEqual(3,f.snapshot.call_count)
        f.text_button.assert_not_called()
        self.assertIsNone(f.matching_dispatch_row(True,[SquadRow(hud_avatar,S.RETURNING)],panel_avatar))
        # Even a missed panel busy badge cannot submit a squad still in the HUD.
        with self.assertRaisesRegex(RuntimeError,'所选队伍已在行军'):
            f._submit_from_panel(queue=3,existing=[row])
        self.assertFalse(any(c.args[0] == '出征' for c in f.text_button.call_args_list))
        self.assertIs(changed,f.hud_avatar(3,changed))
        self.assertNotIn(3,f._hud_avatars)
        self.assertIsNone(f.matching_dispatch_row(True,[row],changed))

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
        for kind in (March,Pixiu,LingEr,FuHu):
            with self.subTest(kind=kind):
                f=self.flow(kind)
                f.panel=Mock(side_effect=[RuntimeError('气泡未出现'),(1,[])])
                self.assertEqual((1,[]),f.ready_dispatch_panel())
                self.assertEqual(2,f.panel.call_count)
                f.click.assert_not_called();f.pipeline.assert_not_called()

        # Map search and read-only inspection are inherited, so new march
        # tasks get the same recognition/recovery rules without copying code.
        for kind in (March,Pixiu,LingEr,FuHu):
            self.assertIs(kind.open_world_search,March.open_world_search)
            self.assertIs(kind.confirm_idle_in_panel,March.confirm_idle_in_panel)
            f=self.flow(kind)
            icon=SimpleNamespace(box=SimpleNamespace(x=30,y=99,w=44,h=42))
            f.recognize=Mock(side_effect=[SimpleNamespace(hit=False,filtered_results=[]),
                                         SimpleNamespace(hit=True,filtered_results=[icon])])
            self.assertTrue(f.open_world_search())
            f.click.assert_called_once()
            params=f.recognize.call_args.args[2]
            self.assertEqual(['Common/March/search_symbol.png'],params.template)
            self.assertEqual([.85],params.threshold)
            f.click.reset_mock();f.templates=Mock(return_value=[icon,icon])
            with patch('agent.custom.action.march.dispatch_panel.time.monotonic',side_effect=[0,0,9]):
                self.assertFalse(f.open_world_search())
            f.click.assert_not_called();f.record_panel_failure.assert_called_once()

    def test_panel_button_type_is_required_before_arrow_recognition(self):
        for kind in (March,Pixiu,LingEr,FuHu):
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
                            (Pixiu,parse_status('5去X:620Y:373')),(LingEr,S.ASSEMBLING),
                            (FuHu,S.OUTBOUND)):
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
        for kind,status in ((March,S.OUTBOUND),(Pixiu,S.OUTBOUND),(LingEr,S.ASSEMBLING),(FuHu,S.OUTBOUND)):
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

        # 最后一次数量检查在 text_button 点击前执行；检查失败时不得恢复并不存在的出征。
        for kind in (March,Pixiu,LingEr,FuHu):
            f=self.flow(kind)
            avatar=np.random.default_rng(102).random((24,24,3))
            panel=(1,[(True,(0,0),avatar)])
            f.allowed_queues=[1];f.panel_busy=[False]
            f.ready_dispatch_panel=Mock(return_value=panel)
            f.panel=Mock(return_value=panel)
            f.zero_disciples=Mock(return_value=False)
            f.text_button=Mock(side_effect=[False,RuntimeError('数量标题仍被遮挡')])
            f.recover_world=Mock();f.reconcile_pending_dispatch=Mock()
            with self.assertRaisesRegex(RuntimeError,'数量标题仍被遮挡'):
                f.dispatch_from_panel(queue=1,existing=[])
            self.assertFalse(f.pending_dispatch)
            f.click.assert_not_called()
            f.recover_world.assert_not_called();f.reconcile_pending_dispatch.assert_not_called()

    def test_disciple_quantity_uses_bar_without_title_and_preserves_zero_guard(self):
        from maa.define import Rect
        from agent.custom.action.march.dispatch_panel import ZeroDisciples
        icon=SimpleNamespace(box=Rect(38,45,48,48))
        button=SimpleNamespace(text='组队',box=Rect(417,278,89,46))
        for quantity in (1846,0):
            f=self.flow(LingEr);f.templates=Mock(return_value=[icon])
            values=[SimpleNamespace(text=f'{quantity}/1846',box=Rect(120,20,116,24))]
            f.ocr=Mock(side_effect=[values,[button]])
            if quantity:
                self.assertTrue(f.text_button('组队'))
                f.click.assert_called_once()
            else:
                with self.assertRaises(ZeroDisciples):
                    f.text_button('组队')
                f.click.assert_not_called()
        f=self.flow(LingEr);f.templates=Mock(return_value=[]);f.ocr=Mock()
        with self.assertRaisesRegex(RuntimeError,'无法唯一确认出征面板人数栏'):
            f.text_button('组队')
        f.click.assert_not_called();f.ocr.assert_not_called()

    def test_only_selected_idle_queue_is_dispatched(self):
        f=self.flow(Pixiu)
        avatars=np.random.default_rng(42).random((4,24,24,3))
        f.allowed_queues=[1,4]
        f.panel_busy=[True,False,False,False]
        f.ready_dispatch_panel=Mock(return_value=(1,[(True,(0,0),a) for a in avatars]))
        f._submit_from_panel=Mock(return_value=MarchHandle(4,avatars[3],MarchTracker(state=S.OUTBOUND)))
        self.assertEqual(4,f.dispatch_from_panel(existing=[]).queue)
        f._submit_from_panel.assert_called_once_with(4,existing=[],timeout=15)

        # Fuhu rotation waits for the next selected squad even if another is idle.
        from agent.custom.action.march.dispatch_panel import NoFreeQueue
        f=self.flow(FuHu)
        f.allowed_queues=[1,4]
        f.allowed_avatars={1:avatars[0],4:avatars[3]}
        handle=MarchHandle(4,avatars[3],MarchTracker(state=S.OUTBOUND))
        f.dispatch=Mock(side_effect=[NoFreeQueue('第 4 队返回中'),handle])
        f.close_dispatch_panel=Mock()
        f.snapshot=Mock(side_effect=[
            (True,[SquadRow(avatars[3],S.RETURNING)],1),
            (False,[],0),
            (True,[SquadRow(avatars[0],S.RETURNING)],1),
            (True,[SquadRow(avatars[0],S.RETURNING)],1)])
        self.assertIs(handle,f.dispatch_next(4))
        self.assertEqual(4,f.snapshot.call_count)
        self.assertEqual([4,4],[c.kwargs['queue'] for c in f.dispatch.call_args_list])
        f.close_dispatch_panel.assert_called_once()

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

        # A search miss during return inspection must be recoverable and must
        # never count completion or submit the same squad again.
        f=self.flow(LingEr)
        avatar=np.random.default_rng(30).random((24,24,3))
        tracker=RallyTracker(state=S.FIGHTING,assembled=True,departed=True,
                             missing_after_departure=3)
        handle=MarchHandle(1,avatar,tracker,panel_avatar=avatar.copy())
        f.snapshot=Mock(return_value=(True,[],0))
        f.locate=Mock(side_effect=[RuntimeError('未找到大地图左下角搜索图标'),None])
        f.recover_world=Mock();f.close_dispatch_panel=Mock()
        f.text_button=Mock(return_value=True);f.open_target_panel=Mock(return_value=True)
        f.ready_dispatch_panel=Mock(return_value=(1,[(True,(0,0),avatar)]))
        f.panel_busy=[False]
        self.assertFalse(f.confirm_returned_in_panel(handle,keep_open=True))
        self.assertEqual(S.FIGHTING,tracker.state)
        self.assertFalse(f.return_panel_open)
        f.recover_world.assert_called_once();f.record_panel_failure.assert_called_once()
        f.text_button.assert_not_called();f.open_target_panel.assert_not_called()
        f.close_dispatch_panel.assert_not_called()
        self.assertTrue(f.confirm_returned_in_panel(handle,keep_open=True))
        self.assertEqual(2,f.ready_dispatch_panel.call_count)
        self.assertTrue(f.return_panel_open)
        f.open_target_panel.assert_called_once_with()
        f.text_button.assert_not_called();f.close_dispatch_panel.assert_not_called()

    def test_rally_recovers_status_when_count_changes(self):
        from maa.define import Rect
        f=self.flow(LingEr)
        avatars=np.random.default_rng(33).random((2,24,24,3))
        states=[S.ASSEMBLING,S.ASSEMBLING]
        header=SimpleNamespace(box=Rect(56,60,48,30))
        anchors=[SimpleNamespace(box=Rect(222,y,31,31)) for y in (16,77)]
        origin=int(f.screenshot.return_value.shape[0]*.18)+90
        def read(image,start,box):
            index=min(range(2),key=lambda i:abs(start+box.y-origin-anchors[i].box.y))
            return SquadRow(avatars[index],states[index]),[str(states[index])]
        f.templates=Mock(return_value=[header]);f.row_anchors=Mock(return_value=anchors)
        f.ocr=Mock(return_value=[SimpleNamespace(text='2/4')])
        f.read_squad_row=Mock(side_effect=read)
        handle=MarchHandle(1,avatars[0],RallyTracker(state=S.ASSEMBLING,assembled=True))
        f.active={1:handle}
        self.assertTrue(f.snapshot()[0])
        # 数量下降且图标漏检时，原位置的头像和状态仍须复核。
        f.row_anchors.return_value=[];f.ocr.return_value=[SimpleNamespace(text='1/4')]
        states[:]=[S.OUTBOUND,None]
        self.assertTrue(f.snapshot()[0])
        self.assertTrue(handle.tracker.departed)
        self.assertEqual(S.OUTBOUND,handle.tracker.state)
        states[0]=None
        self.assertFalse(f.snapshot()[0])
        self.assertEqual(0,handle.tracker.missing_observations)

    def test_squad_count_wide_read_requires_the_header_line(self):
        from maa.define import Rect
        header=SimpleNamespace(box=Rect(56,60,48,30))
        avatars=np.random.default_rng(34).random((2,24,24,3))
        cases=(([(221,65,34,20)],True), ([(221,200,34,20)],False),
               ([(100,65,34,20)],False), ([(205,65,20,20),(235,65,20,20)],False))
        for boxes,expected in cases:
            with self.subTest(boxes=boxes):
                f=self.flow(March);f.templates=Mock(return_value=[header])
                f.row_anchors=Mock(return_value=[SimpleNamespace(box=Rect(225,y,31,31))
                                                 for y in (14,76)])
                f.read_squad_row=Mock(side_effect=[(SquadRow(a,None),['采集中']) for a in avatars])
                def ocr(crop,expected=None,only_rec=False):
                    if crop.shape[0]>100:
                        return [SimpleNamespace(text='2/4',box=Rect(*box)) for box in boxes]
                    # 回放实际失败：窄区域把 2/4 错读成 214，不能据此猜测数量。
                    return [SimpleNamespace(text='214')]
                f.ocr=Mock(side_effect=ocr)
                valid,rows,count=f.snapshot()
                self.assertEqual(expected,valid)
                self.assertEqual(2,len(rows))
                if expected:
                    self.assertEqual(2,count)
                    self.assertIn('宽区域',f.snapshot_reason)

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
        f.recognize=Mock(return_value=SimpleNamespace(hit=False,filtered_results=[]))
        self.assertIsNone(f.target_dispatch_point(f.screenshot()))

        # 地图背景干扰完整图标时，遮罩图标和“集结”文字均通过才能继续。
        f.recognize.return_value=SimpleNamespace(hit=True,filtered_results=[icon])
        f.ocr.return_value=[SimpleNamespace(text='集结')]
        f.click=Mock();f.pause=Mock()
        self.assertTrue(f.open_target_panel())
        f.click.assert_called_once()
        self.assertEqual(4,f.recognize.call_count)
        f.click.reset_mock();f.ocr.return_value=[]
        with patch('agent.custom.action.march.dispatch_panel.time.monotonic',side_effect=[0,0,9]):
            self.assertFalse(f.open_target_panel())
        f.click.assert_not_called()
        f.recognize.return_value=SimpleNamespace(hit=True,filtered_results=[icon,icon])
        self.assertIsNone(f.target_dispatch_point(f.screenshot()))

        with self.assertRaisesRegex(RuntimeError,'加减按钮'):
            f.search_level()

        f.open_world_search=Mock(return_value=True)
        f.region_text=Mock(side_effect=[False,False,True,True])
        f.adjust_level=Mock();f.pause=Mock()
        f.target_dispatch_point=Mock(return_value=(100,200))
        f.locate(None)
        f.open_world_search.assert_called_once_with()
        f.pause.assert_called_once_with(.3)
        f.adjust_level.assert_called_once_with(8)

    def test_rally_waits_for_the_whole_batch_before_refilling(self):
        f=self.flow(LingEr);f.pipeline.return_value=True
        a,b=np.random.default_rng(31).random((2,24,24,3))
        handles=[MarchHandle(q,avatar,RallyTracker(state=S.ASSEMBLING,assembled=True),
                             panel_avatar=avatar.copy()) for q,avatar in ((1,a),(4,b),(1,a))]
        # 复现第一队完成而第四队仍在集结；此时打开搜索补派第一队会遮住第四队的短途行军和返回。
        frames=iter([
            [],[SquadRow(a,S.ASSEMBLING)],
            [SquadRow(a,S.OUTBOUND),SquadRow(b,S.ASSEMBLING)],
            [SquadRow(a,S.RETURNING),SquadRow(b,S.ASSEMBLING)],
            *[[SquadRow(b,S.ASSEMBLING)]]*3,
            [SquadRow(b,S.OUTBOUND)],[SquadRow(b,S.RETURNING)],[],[],[],
            [SquadRow(a,S.OUTBOUND)],[SquadRow(a,S.RETURNING)],[],[],[]])
        def snapshot():
            rows=next(frames)
            f.observe_active(True,rows)
            return True,rows,len(rows)
        f.snapshot=Mock(side_effect=snapshot)
        f.confirm_returned_in_panel=Mock()
        def dispatch(*args,**kwargs):
            index=f.dispatch.call_count-1
            if index == 2:
                self.assertTrue(all(h.tracker.state == S.COMPLETED for h in handles[:2]))
            self.assertEqual(handles[index].queue,kwargs['queue'])
            return handles[index]
        f.dispatch=Mock(side_effect=dispatch)
        case=SimpleNamespace(parameters={'rally_count':3,'rally_queues':[1,4]})
        with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
            self.assertIn('已完成 3 次',run_ling_er(f.engine,case))
        self.assertEqual([1,4,1],[c.kwargs['queue'] for c in f.dispatch.call_args_list])
        self.assertTrue(all(h.tracker.state == S.COMPLETED for h in handles))
        f.confirm_returned_in_panel.assert_not_called()
        f.record_panel_failure.assert_not_called()

        # 入口识别失败时保存现场，不能搜索或出征。
        f=self.flow(LingEr);f.dispatch=Mock();f.locate=Mock();f.snapshot=Mock()
        with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
            with self.assertRaisesRegex(RuntimeError,'启动时未能确认大地图默认界面'):
                run_ling_er(f.engine,case)
        f.record_panel_failure.assert_called_once_with(f.screenshot.return_value)
        f.snapshot.assert_not_called();f.locate.assert_not_called();f.dispatch.assert_not_called()

    def test_rally_missing_without_departure_is_inspected_but_never_counted(self):
        for idle in (True,False):
            with self.subTest(idle=idle):
                f=self.flow(LingEr);f.pipeline.return_value=True
                a,b=np.random.default_rng(32).random((2,24,24,3))
                handles=[MarchHandle(q,avatar,RallyTracker(state=S.ASSEMBLING,assembled=True),
                                     panel_avatar=avatar.copy()) for q,avatar in ((1,a),(4,b))]
                frames=iter([[],[SquadRow(a,S.ASSEMBLING)],
                             *[[SquadRow(b,S.ASSEMBLING)]]*30,
                             [SquadRow(b,S.OUTBOUND)],[SquadRow(b,S.RETURNING)],[],[],[]])
                def snapshot():
                    rows=next(frames)
                    f.observe_active(True,rows)
                    return True,rows,len(rows)
                f.snapshot=Mock(side_effect=snapshot)
                f.dispatch=Mock(side_effect=handles)
                def inspect(handle,**kwargs):
                    self.assertIs(handles[0],handle)
                    # 第四队仍在执行时，不能用面板遮住小队列表。
                    self.assertEqual(S.COMPLETED,handles[1].tracker.state)
                    self.assertFalse(handles[0].tracker.ready_for_return_check)
                    return idle
                f.confirm_idle_in_panel=Mock(side_effect=inspect)
                f.confirm_returned_in_panel=Mock()
                case=SimpleNamespace(parameters={'rally_count':3,'rally_queues':[1,4]})
                with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
                    with self.assertRaisesRegex(RuntimeError,'本次未计数、未重复组队') as caught:
                        run_ling_er(f.engine,case)
                self.assertIn('无法区分集结取消与行军漏采' if idle else '未能连续确认',str(caught.exception))
                self.assertIn('已完成 1/3 次',str(caught.exception))
                self.assertEqual(S.ASSEMBLING,handles[0].tracker.state)
                self.assertEqual(2,f.dispatch.call_count)
                f.confirm_idle_in_panel.assert_called_once_with(handles[0],select_target=f.locate)
                f.confirm_returned_in_panel.assert_not_called()
                f.record_panel_failure.assert_called_once_with(f.screenshot.return_value)
                self.assertTrue(any('最后可靠可见=' in c.args[0] for c in f.engine.log.call_args_list))

    def test_fu_hu_rotates_on_its_own_returning_state(self):
        f=self.flow(FuHu)
        a,b=np.random.default_rng(24).random((2,24,24,3))
        handles=[MarchHandle(1,a,MarchTracker(state=S.OUTBOUND),last_count=2),
                 MarchHandle(2,b,MarchTracker(state=S.OUTBOUND),last_count=1),
                 MarchHandle(1,a,MarchTracker(state=S.OUTBOUND),last_count=1)]
        def dispatch(queue):
            index=f.dispatch_next.call_count-1
            self.assertEqual(handles[index].queue,queue)
            if index:
                self.assertEqual(S.RETURNING,handles[index-1].tracker.state)
            return handles[f.dispatch_next.call_count-1]
        f.dispatch_next=Mock(side_effect=dispatch)
        f.confirm_returned_in_panel=Mock(return_value=False)
        absent=(True,[],0)
        f.snapshot=Mock(side_effect=[
            (True,[SquadRow(a,S.OUTBOUND),SquadRow(b,S.RETURNING)],2),
            (False,[SquadRow(a,S.RETURNING)],1),  # Unreliable status cannot advance.
            (True,[SquadRow(a,S.OUTBOUND)],1),
            absent,absent,absent,  # Absence before a return cannot complete the run.
            (True,[SquadRow(a,S.RETURNING)],1),
            (True,[SquadRow(a,S.RETURNING)],1),  # The previous squad is still returning.
            (True,[SquadRow(b,S.FIGHTING)],1),
            (True,[SquadRow(b,S.RETURNING)],1),
            (True,[SquadRow(a,S.FIGHTING)],1),
            (True,[SquadRow(a,S.RETURNING)],1)])
        case=SimpleNamespace(parameters={'attack_count':3,'attack_queues':[1,2]})
        f.wait=Mock()
        with patch('agent.custom.action.auto_fu_hu.FuHu',return_value=f):
            self.assertIn('已完成 3 次',run_fu_hu(f.engine,case))
        self.assertEqual([1,2],f.allowed_queues)
        self.assertEqual([1,2,1],[c.args[0] for c in f.dispatch_next.call_args_list])
        self.assertTrue(all(h.tracker.state==S.RETURNING for h in handles))
        f.wait.assert_not_called()
        f.wait_until_returning=Mock(side_effect=TimeoutError('返回未确认'))
        f.dispatch_next=Mock(return_value=handles[0])
        with patch('agent.custom.action.auto_fu_hu.FuHu',return_value=f):
            with self.assertRaisesRegex(TimeoutError,'返回未确认'):
                run_fu_hu(f.engine,case)
        f.dispatch_next.assert_called_once()

    def test_fu_hu_recovers_map_text_in_status_only_on_agreement(self):
        from maa.define import Rect
        image=np.zeros((1306,720,3),dtype=np.uint8)
        anchor=Rect(225,300,31,31)
        for texts,expected in (
            (['返回01724653','返回01724653','导返回017'],S.RETURNING),
            (['导返回01724653','返回01724653','导返回017'],S.RETURNING),
            (['导战斗中1724653','战斗中1724653','导战斗中'],S.FIGHTING),
            (['返回龙王费日','返回龙王费日','返回龙'],S.RETURNING),
            (['返回龙生[费日','返回龙王费日','返回龙'],S.RETURNING),
            (['战斗中心主了','战斗中心王','战斗中人'],S.FIGHTING),
            (['未知返回01724653','00:17:24','返回017'],None),
            (['返回01724653','战斗中1724653','未知'],None),
            (['返回龙王','战斗中心王','返回龙'],None),
            (['返回00:17:24','返回00:17:24','00:17:24'],None),
        ):
            f=self.flow(FuHu)
            f.ocr=Mock(side_effect=[[SimpleNamespace(text=text)] for text in texts])
            row,observed=f.read_squad_row(image,0,anchor)
            self.assertEqual(expected,row.status)
            self.assertEqual(texts,observed)
        # The task-specific fallback must not relax other march tasks.
        f=self.flow(March)
        f.ocr=Mock(side_effect=[[SimpleNamespace(text=text)] for text in
                               ['返回01724653','返回01724653','导返回017']])
        self.assertIsNone(f.read_squad_row(image,0,anchor)[0].status)

        # Replay the twentieth dispatch's actual status reads through the
        # return wait, so Chinese map names cannot leave the squad outbound.
        f=self.flow(FuHu)
        f.ocr=Mock(side_effect=[[SimpleNamespace(text=text)] for text in
                               ['返回龙王费日','返回龙王费日','返回龙']])
        frame=np.random.default_rng(26).integers(0,256,image.shape,dtype=np.uint8)
        row,_=f.read_squad_row(frame,0,anchor)
        handle=MarchHandle(2,row.avatar,MarchTracker(state=S.OUTBOUND),last_count=1)
        f.snapshot=Mock(return_value=(True,[row],1))
        self.assertIs(handle,f.wait_until_returning(handle))
        self.assertEqual(S.RETURNING,handle.tracker.state)
        f.snapshot.assert_called_once()

    def test_fu_hu_recovers_missed_return_only_after_same_squad_is_idle(self):
        f=self.flow(FuHu)
        a,b=np.random.default_rng(28).random((2,24,24,3))
        handle=MarchHandle(2,a,MarchTracker(state=S.FIGHTING),last_count=1,panel_avatar=a.copy())
        absent=(True,[],0)
        f.snapshot=Mock(side_effect=[(True,[SquadRow(a,None)],1),absent,absent,
                                     (False,[],0),absent,absent,absent])
        f.confirm_returned_in_panel=Mock(return_value=True)
        f.dispatch=Mock()
        self.assertIs(handle,f.wait_until_returning(handle))
        self.assertEqual(S.COMPLETED,handle.tracker.state)
        f.confirm_returned_in_panel.assert_called_once_with(handle)
        self.assertEqual(7,f.snapshot.call_count)
        f.dispatch.assert_not_called()

        # Inspect the tracked queue twice. A busy badge or changed portrait
        # on either read must reject the fallback, even if other squads are idle.
        for busy_flags,portraits,expected in (
            ([False,False],[a,a],True),
            ([False,True],[a,a],False),
            ([False,False],[a,b],False),
        ):
            f=self.flow(FuHu)
            f.locate=Mock();f.open_target_panel=Mock(return_value=True)
            f.recover_world=Mock();f.dispatch=Mock();f.text_button=Mock()
            reads=iter(zip(busy_flags,portraits))
            def panel():
                busy,avatar=next(reads)
                f.panel_busy=[False,busy,False,False]
                return 1,[(True,(0,0),b),(True,(0,0),avatar)]
            f.ready_dispatch_panel=Mock(side_effect=panel)
            self.assertEqual(expected,f.confirm_returned_in_panel(handle))
            self.assertEqual(2,f.ready_dispatch_panel.call_count)
            f.dispatch.assert_not_called();f.text_button.assert_not_called()
            f.recover_world.assert_called_once()

    def test_fu_hu_relocates_once_only_when_first_click_leaves_world(self):
        f=self.flow(FuHu)
        f.pipeline.return_value=True
        f.recovery_state=Mock(return_value='大世界默认态')
        f.target_dispatch_point.side_effect=[None,(300,970)]
        with patch('agent.custom.action.auto_fu_hu.time.monotonic',
                   side_effect=[0,0,11,12,12]):
            f.locate(None)
        self.assertEqual(2,f.pipeline.call_count)
        f.click.assert_not_called()
        f.pipeline.reset_mock()
        f.recovery_state.return_value='目标弹窗'
        f.target_dispatch_point.side_effect=None
        with patch('agent.custom.action.auto_fu_hu.time.monotonic',side_effect=[0,0,11]):
            with self.assertRaisesRegex(RuntimeError,'未确认伏虎降妖'):
                f.locate(None)
        f.pipeline.assert_called_once_with('伏虎降妖定位入口')

    def test_fu_hu_finishes_on_confirmed_missing_icon_without_dispatching_again(self):
        f=self.flow(FuHu)
        f.recognize=Mock(side_effect=[SimpleNamespace(hit=False) for _ in range(3)])
        f.recovery_state=Mock(return_value='大世界默认态')
        with self.assertRaises(FuHuFinished):
            FuHu.check_icon_completion(f)
        self.assertEqual(3,f.recognize.call_count)
        f.pipeline.assert_not_called();f.click.assert_not_called()
        # An icon reappearing or an obstructing popup cannot complete the task.
        f.recognize=Mock(side_effect=[SimpleNamespace(hit=False),SimpleNamespace(hit=True)])
        FuHu.check_icon_completion(f)
        f.recognize=Mock(return_value=SimpleNamespace(hit=False))
        f.recovery_state.return_value='出征弹窗'
        FuHu.check_icon_completion(f)
        f.recognize.assert_called_once()

        case=SimpleNamespace(parameters={'attack_count':25,'attack_queues':[1,2]})
        f.dispatch_next=Mock(side_effect=FuHuFinished('图标消失'))
        f.wait_until_returning=Mock()
        with patch('agent.custom.action.auto_fu_hu.FuHu',return_value=f):
            self.assertIn('已完成：任务图标消失',run_fu_hu(f.engine,case))
        f.dispatch_next.assert_called_once();f.wait_until_returning.assert_not_called()

        # Also finish if the icon disappears while the last dispatched squad
        # is still fighting; no return frame or extra dispatch is required.
        f=self.flow(FuHu)
        handle=MarchHandle(1,np.zeros((24,24,3)),MarchTracker(state=S.FIGHTING))
        f.dispatch_next=Mock(return_value=handle)
        f.check_icon_completion.side_effect=FuHuFinished('图标消失')
        f.poll_return=Mock()
        with patch('agent.custom.action.auto_fu_hu.FuHu',return_value=f):
            self.assertIn('已完成：任务图标消失',run_fu_hu(f.engine,case))
        f.dispatch_next.assert_called_once();f.poll_return.assert_not_called()
        f.close_dispatch_panel=Mock()
        f.snapshot=Mock()
        with self.assertRaises(FuHuFinished):
            f.close_and_wait_for_return(1,900)
        f.close_dispatch_panel.assert_called_once();f.snapshot.assert_not_called()


if __name__ == '__main__':
    unittest.main()
