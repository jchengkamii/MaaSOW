from __future__ import annotations
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
from agent.custom.action.auto_ling_er import LingEr, RallyTracker, rally_level, rally_queues, run, NoFreeQueue, ZeroDisciples
from agent.custom.action.march.march import March, MarchHandle, SquadRow, similarity
from agent.custom.action.march.state import MarchState as S, parse_status
from agent.custom.action.run_configured_case import parse_rally_options, worker_command_with_options, selected_rally_queues
from generate_interface import generate

class LingErTests(unittest.TestCase):
    def test_lifecycle_requires_assembly_departure_return_and_reliable_disappearance(self):
        t=RallyTracker()
        for state in (S.ASSEMBLING,S.OUTBOUND,S.RETURNING):
            self.assertFalse(t.observe(visible=True,status=state,reliable=True))
        self.assertFalse(t.observe(visible=False,status=None,reliable=True,count_decreased=True))
        self.assertFalse(t.observe(visible=False,status=None,reliable=False,count_decreased=True))
        self.assertEqual(0,t.missing)
        self.assertEqual([False,False,True],[t.observe(visible=False,status=None,reliable=True,count_decreased=True) for _ in range(3)])

    def test_cancelled_or_unobserved_rally_never_counts(self):
        for states in ((S.ASSEMBLING,S.RETURNING),(S.OUTBOUND,S.RETURNING),(S.ASSEMBLING,S.OUTBOUND)):
            t=RallyTracker()
            for s in states:t.observe(visible=True,status=s,reliable=True)
            for _ in range(5):self.assertFalse(t.observe(visible=False,status=None,reliable=True,count_decreased=True))
        self.assertEqual(S.ASSEMBLING,parse_status('集结中...'))
        self.assertEqual(S.OUTBOUND,parse_status('出征'))
        self.assertIsNone(parse_status('00:00:55'))

    def test_level_adjustment_both_directions_and_unchanged_boundary(self):
        for values,target,names in (([1,2,3,3],3,['plus','plus']),([4,3,2,1,1],1,['minus']*3),([1,1],1,[])):
            f=LingEr.__new__(LingEr);f.search_level=Mock(side_effect=values);f.pause=Mock();f.icon_button=Mock(return_value=True)
            f.adjust_level(target)
            self.assertEqual(names,[c.args[0] for c in f.icon_button.call_args_list])
        f.search_level=Mock(side_effect=[4,4]);f.icon_button.reset_mock()
        with self.assertRaises(RuntimeError):f.adjust_level(5)
        self.assertEqual(1,f.icon_button.call_count)

    def flow(self):
        f=LingEr.__new__(LingEr);f.engine=Mock();f.tasker=Mock();f.pause=Mock();f.screenshot=Mock();f.snapshot=Mock(return_value=(True,[],0))
        avatar=np.random.default_rng(88).random((24,24,3))
        f.panel=Mock(return_value=(2,[(True,(100,100),avatar)]*4));f.panel_busy=[False]*4
        return f,avatar

    def test_selected_queue_is_forwarded_to_common_dispatch(self):
        f,avatar=self.flow()
        f.allowed_queues=[2,3]
        h=MarchHandle(2,avatar,RallyTracker(state=S.ASSEMBLING),1)
        with patch.object(March,'dispatch_from_panel',return_value=h) as dispatch:
            result=f.dispatch_from_panel(queue=2,existing=[])
        self.assertEqual(2,dispatch.call_args.args[1])
        self.assertTrue(result.tracker.assembled)
        self.assertFalse(result.tracker.departed)

    def test_busy_first_never_falls_back_to_free_second(self):
        f,_=self.flow();f.panel_busy=[True,False,False,False]
        with patch.object(March,'dispatch_from_panel') as dispatch:
            with self.assertRaises(NoFreeQueue):f.dispatch_from_panel(existing=[])
        dispatch.assert_not_called()

    def test_stamina_retry_requires_explicit_prompt_and_checkbox(self):
        f,avatar=self.flow();f.pipeline=Mock(return_value=True);f.engine.auto_stamina=True
        h=MarchHandle(1,avatar,RallyTracker(state=S.ASSEMBLING),1)
        with patch.object(March,'dispatch_from_panel',side_effect=[TimeoutError(),h]) as dispatch:
            f.dispatch_from_panel(existing=[])
            self.assertEqual(2,dispatch.call_count)
        f.engine._try_auto_stamina.assert_called_once()
        f.engine.auto_stamina=False
        with patch.object(March,'dispatch_from_panel',side_effect=TimeoutError()) as dispatch:
            with self.assertRaisesRegex(RuntimeError,'未勾选'):f.dispatch_from_panel(existing=[])
            self.assertEqual(1,dispatch.call_count)
        f.pipeline=Mock(return_value=False)
        with patch.object(March,'dispatch_from_panel',side_effect=TimeoutError()) as dispatch:
            with self.assertRaises(TimeoutError):f.dispatch_from_panel(existing=[])
            self.assertEqual(1,dispatch.call_count)

    def scheduler_flow(self):
        f=Mock()
        events=[]
        tick=[0]
        ages={}
        def dispatch(*args,queue,**kwargs):
            events.append(('dispatch',queue))
            handle=MarchHandle(queue,np.zeros((24,24,3)),RallyTracker(state=S.ASSEMBLING,assembled=True),1)
            ages[id(handle)]=0
            return handle
        def snapshot():
            tick[0]+=1
            for q,h in f.active.items():
                ages[id(h)]+=1
                age=ages[id(h)]
                if age<=2:
                    h.tracker.observe(visible=True,status=S.OUTBOUND,reliable=True)
                elif age==3:
                    h.tracker.observe(visible=True,status=S.RETURNING,reliable=True)
                elif h.tracker.observe(visible=False,status=None,reliable=True,count_decreased=True):
                    events.append(('returned',q))
            return True,[],0
        f.snapshot.side_effect=snapshot
        f.dispatch.side_effect=dispatch
        return f,events

    def test_default_queue_waits_for_return_before_reuse(self):
        f,events=self.scheduler_flow()
        with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
            result=run(Mock(),SimpleNamespace(parameters={'rally_count':2}))
        self.assertEqual([('dispatch',1),('returned',1)]*2,events)
        self.assertEqual(1,f.level)
        self.assertIn('2 次',result)

    def test_three_queues_overlap_and_total_never_overshoots(self):
        f,events=self.scheduler_flow()
        with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
            run(Mock(),SimpleNamespace(parameters={'rally_count':7,'rally_queues':[1,2,3]}))
        self.assertEqual([('dispatch',1),('dispatch',2),('dispatch',3)],events[:3])
        self.assertEqual(7,sum(kind=='dispatch' for kind,q in events))
        self.assertEqual(7,sum(kind=='returned' for kind,q in events))
        self.assertNotIn(4,[q for kind,q in events])
        in_flight=set()
        for kind,q in events:
            if kind=='dispatch':
                self.assertNotIn(q,in_flight)
                in_flight.add(q)
            else:in_flight.remove(q)
        self.assertFalse(in_flight)

    def test_budget_smaller_than_selection_and_only_four_selected(self):
        for queues,count,expected in (([1,2,3],2,[1,2]),([4],2,[4,4])):
            f,events=self.scheduler_flow()
            with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
                run(Mock(),SimpleNamespace(parameters={'rally_count':count,'rally_queues':queues}))
            self.assertEqual(expected,[q for kind,q in events if kind=='dispatch'])

    def test_busy_selected_queue_does_not_block_other_selected_squads(self):
        f,events=self.scheduler_flow()
        dispatch=f.dispatch.side_effect
        def busy(*a,queue,**kw):
            if queue==1:
                f.blocked[1]=(None,0)
                raise NoFreeQueue()
            return dispatch(*a,queue=queue,**kw)
        f.dispatch.side_effect=busy
        with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
            run(Mock(),SimpleNamespace(parameters={'rally_count':2,'rally_queues':[1,2,3]}))
        self.assertEqual([2,3],[q for kind,q in events if kind=='dispatch'])
        f.close_dispatch_panel.assert_called_once()

    def test_incomplete_rally_stops_without_another_dispatch(self):
        f,events=self.scheduler_flow()
        snapshot=f.snapshot.side_effect
        def timeout():
            if f.active:raise TimeoutError()
            return snapshot()
        f.snapshot.side_effect=timeout
        with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
            with self.assertRaises(TimeoutError):run(Mock(),SimpleNamespace(parameters={'rally_count':2}))
        self.assertEqual(1,f.dispatch.call_count)

    def test_unselected_and_active_queue_are_never_submitted(self):
        f,avatar=self.flow();f.allowed_queues=[1,3]
        with patch.object(March,'dispatch_from_panel') as dispatch:
            with self.assertRaises(ValueError):f.dispatch_from_panel(queue=4,existing=[])
            f.active={3:Mock()}
            with self.assertRaises(NoFreeQueue):f.dispatch_from_panel(queue=3,existing=[])
        dispatch.assert_not_called()
        f.panel.assert_not_called()

    def test_shared_snapshot_tracks_reordering_and_same_total_disappearance(self):
        f,_=self.flow()
        a,b,c=np.random.default_rng(6).random((3,24,24,3))
        h1=MarchHandle(1,a,RallyTracker(state=S.ASSEMBLING,assembled=True),2)
        h2=MarchHandle(2,b,RallyTracker(state=S.ASSEMBLING,assembled=True),2)
        f.active={1:h1,2:h2}
        f.observe_active(True,[SquadRow(b,S.OUTBOUND),SquadRow(a,S.OUTBOUND)])
        f.observe_active(True,[SquadRow(a,S.RETURNING),SquadRow(b,S.OUTBOUND)])
        # An unrelated newly visible queue keeps the total at two.
        rows=[SquadRow(c,S.OUTBOUND),SquadRow(b,S.OUTBOUND)]
        f.observe_active(True,rows)
        f.observe_active(False,[])
        self.assertEqual(0,h1.tracker.missing)
        for _ in range(3):f.observe_active(True,rows)
        self.assertEqual(S.COMPLETED,h1.tracker.state)
        self.assertEqual(S.OUTBOUND,h2.tracker.state)

    def test_ambiguous_shared_portraits_do_not_advance_states(self):
        f,a=self.flow()
        f.active={q:MarchHandle(q,a,RallyTracker(state=S.ASSEMBLING,assembled=True),2) for q in (1,2)}
        f.observe_active(True,[SquadRow(a,S.OUTBOUND)])
        self.assertTrue(all(h.tracker.state==S.ASSEMBLING for h in f.active.values()))

    def test_queue_checkboxes_all_combinations_and_empty_rejection(self):
        generated=generate()
        option=generated['option']['玲儿集结队列']
        self.assertEqual(['1'],option['default_case'])
        self.assertEqual(['1','2','3','4'],[item['label'] for item in option['cases']])
        task=next(t for t in generated['task'] if t['name']=='auto_ling_er')
        for bits in range(16):
            nodes={k:dict(v) for k,v in task['pipeline_override'].items()}
            selected=[q for q in range(1,5) if bits & (1 << (q-1))]
            for q in selected:nodes.update(option['cases'][q-1]['pipeline_override'])
            context=Mock();context.get_node_data.side_effect=nodes.get
            if selected:
                self.assertEqual(selected,selected_rally_queues(context))
            else:
                with self.assertRaises(ValueError):selected_rally_queues(context)
        for bad in ([],[True],[0],[5],[1,1],'','1,5',None):
            with self.assertRaises(ValueError):rally_queues(bad)
        self.assertEqual([1,2,3],rally_queues('3,1,2'))
        self.assertEqual(['--rally-queues','1,2,3'],worker_command_with_options('auto_ling_er',True,rally_queues=[1,2,3])[-2:])

    def test_worker_delivers_selection_and_rejects_wrong_case(self):
        from agent.worker import execute
        with patch('agent.worker.AutomationEngine') as engine, patch('agent.worker.AutomationMutex'), patch('agent.worker._emit_result'):
            engine.return_value.execute_case.return_value=SimpleNamespace(status='passed',message='ok',elapsed=0)
            self.assertEqual(0,execute('auto_ling_er',rally_queues='1,2,3'))
            self.assertEqual([1,2,3],engine.return_value.execute_case.call_args.args[0].parameters['rally_queues'])
            engine.reset_mock()
            self.assertEqual(1,execute('auto_pixiu',rally_queues='1,2,3'))
            engine.assert_not_called()

    def test_short_rally_combat_disappearance_resumes_loop_after_panel_confirmation(self):
        # Replay the observed run: assembly -> combat -> reliable 0/3,
        # with no outbound/return frames sampled.
        f,events=self.scheduler_flow()
        f.confirm_returned_in_panel=Mock(return_value=True)
        def snapshot():
            for q,h in f.active.items():
                if h.tracker.state==S.ASSEMBLING:
                    h.tracker.observe(visible=True,status=S.FIGHTING,reliable=True)
                else:
                    h.tracker.observe(visible=False,status=None,reliable=True,count_decreased=True)
            return True,[],0
        f.snapshot.side_effect=snapshot
        with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
            result=run(Mock(),SimpleNamespace(parameters={'rally_count':2}))
        self.assertEqual([('dispatch',1),('dispatch',1)],events)
        self.assertEqual(2,f.confirm_returned_in_panel.call_count)
        self.assertIn('2 次',result)

    def test_panel_return_confirmation_requires_combat_identity_and_two_free_reads(self):
        for busy, same_avatar, expected in ((False,True,True),(True,True,False),(False,False,False)):
            f,a=self.flow()
            f.locate=Mock();f.text_button=Mock(return_value=True);f.close_dispatch_panel=Mock()
            f.panel_busy[0]=busy
            h=MarchHandle(1,a if same_avatar else np.random.default_rng(9).random((24,24,3)),
                          RallyTracker(state=S.FIGHTING,assembled=True,departed=True,fought=True,missing_after_departure=3),1,
                          panel_avatar=a if same_avatar else np.random.default_rng(9).random((24,24,3)))
            self.assertEqual(expected,f.confirm_returned_in_panel(h))
            self.assertEqual(2 if expected else 1,f.panel.call_count)
            f.text_button.assert_called_once_with('进攻')  # Opens the panel; never submits 组队.
            f.close_dispatch_panel.assert_called_once()
        h.tracker.fought=False
        h.tracker.departed=False
        f.locate.reset_mock()
        self.assertFalse(f.confirm_returned_in_panel(h))
        f.locate.assert_not_called()

    def test_combat_disappearance_counter_resets_on_bad_frames_or_reappearance(self):
        t=RallyTracker(assembled=True)
        t.observe(visible=True,status=S.FIGHTING,reliable=True)
        self.assertTrue(t.departed)
        t.observe(visible=False,status=None,reliable=True,count_decreased=True)
        self.assertEqual(1,t.missing_after_departure)
        t.observe(visible=False,status=None,reliable=False,count_decreased=True)
        self.assertEqual(0,t.missing_after_departure)
        t.observe(visible=False,status=None,reliable=True,count_decreased=True)
        t.observe(visible=True,status=None,reliable=True)
        self.assertEqual(0,t.missing_after_departure)
        self.assertEqual(S.FIGHTING,t.state)

    def test_status_noise_accepts_only_bounded_trailing_punctuation(self):
        for raw,expected in [('战斗中##',S.FIGHTING),('战斗中＃＃',S.FIGHTING),
                             ('集结中·>>>>',S.ASSEMBLING),('战斗中>>>',S.FIGHTING),('返回…',S.RETURNING),('出征...',S.OUTBOUND),('集结中……',S.ASSEMBLING)]:
            self.assertEqual(expected,parse_status(raw))
        for raw in ('战斗中00:00:02','返回00:00:01','未返回','战斗中失败','战斗中123','##战斗中','战斗中#######'):
            self.assertIsNone(parse_status(raw))

    def test_real_two_round_log_trace_keeps_looping_after_noisy_combat(self):
        traces=json.loads((Path(__file__).parent/'data/ling_er_loop_trace.json').read_text(encoding='utf-8'))
        self.assertTrue(any(frame['text']=='战斗中##' for frame in traces[1]))
        f,events=self.scheduler_flow()
        dispatch=f.dispatch.side_effect
        frame_index={}
        round_index=[0]
        def send(*args,queue,**kwargs):
            h=dispatch(*args,queue=queue,**kwargs)
            frame_index[id(h)]=[round_index[0],0]
            round_index[0]+=1
            return h
        def snapshot():
            for h in f.active.values():
                round_no,index=frame_index[id(h)]
                self.assertLess(index,len(traces[round_no]), 'Task stalled after the recorded squad disappearance')
                raw=traces[round_no][index]['text']
                frame_index[id(h)][1]+=1
                h.tracker.observe(visible=raw!='0/3',status=parse_status(raw),reliable=True,count_decreased=raw=='0/3')
            return True,[],0
        f.dispatch.side_effect=send
        f.snapshot.side_effect=snapshot
        f.confirm_returned_in_panel=Mock(return_value=True)
        with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
            result=run(Mock(),SimpleNamespace(parameters={'rally_count':2}))
        self.assertEqual([('dispatch',1),('dispatch',1)],events)
        self.assertEqual(2,f.confirm_returned_in_panel.call_count)
        self.assertIn('2 次',result)

    def test_unconfirmed_disappearance_does_not_wait_for_an_hour(self):
        f,events=self.scheduler_flow()
        def snapshot():
            for h in f.active.values():
                h.tracker.observe(visible=False,status=None,reliable=True,count_decreased=True)
            return True,[],0
        f.snapshot.side_effect=snapshot
        with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
            with self.assertRaisesRegex(RuntimeError,'连续消失 30 次'):
                run(Mock(),SimpleNamespace(parameters={'rally_count':2}))
        self.assertEqual(1,f.dispatch.call_count)
        f.confirm_returned_in_panel.assert_not_called()
        self.assertLessEqual(f.snapshot.call_count,31)

    def test_panel_confirmation_uses_saved_panel_avatar_not_hud_avatar(self):
        f,panel_avatar=self.flow()
        hud_avatar=np.random.default_rng(345).random((24,24,3))
        self.assertLess(similarity(panel_avatar,hud_avatar),.65)
        f.locate=Mock();f.text_button=Mock(return_value=True);f.close_dispatch_panel=Mock()
        h=MarchHandle(2,hud_avatar,RallyTracker(state=S.FIGHTING,assembled=True,departed=True,
                      fought=True,missing_after_departure=3),1,panel_avatar=panel_avatar.copy())
        self.assertTrue(f.confirm_returned_in_panel(h))
        self.assertEqual(2,f.panel.call_count)
        self.assertIs(h.avatar,hud_avatar)
        f.text_button.assert_called_once_with('进攻')

    def test_multi_queue_recovery_does_not_hide_other_squads_and_loops(self):
        f=Mock();events=[];age={}
        panels=np.random.default_rng(415).random((4,24,24,3))
        portraits=np.random.default_rng(416).random((4,24,24,3))
        f.panel_busy=[False]*4
        f.panel.return_value=(1,[(True,(i,0),a) for i,a in enumerate(panels)])
        f.text_button.return_value=True
        def dispatch(*args,queue,**kw):
            events.append(('dispatch',queue))
            h=MarchHandle(queue,portraits[queue-1],RallyTracker(state=S.ASSEMBLING,assembled=True),
                          panel_avatar=panels[queue-1].copy())
            age[id(h)]=0
            return h
        def snapshot():
            for q,h in f.active.items():
                age[id(h)]+=1
                step=age[id(h)]
                combat_at=10 if q==1 else 2
                if step<combat_at:
                    h.tracker.observe(visible=True,status=parse_status('集结中·>>>>'),reliable=True)
                elif step==combat_at:
                    h.tracker.observe(visible=True,status=S.FIGHTING,reliable=True)
                else:
                    h.tracker.observe(visible=False,status=None,reliable=True,count_decreased=True)
            return True,[],0
        def confirm(h, **kwargs):
            self.assertTrue(all(other.tracker.state==S.COMPLETED or other.tracker.missing_observations>=3
                                for other in f.active.values()))
            self.assertLess(similarity(h.avatar,h.panel_avatar),.65)
            result=LingEr.confirm_returned_in_panel(f,h,**kwargs)
            events.append(('confirmed',h.queue))
            return result
        f.dispatch.side_effect=dispatch;f.dispatch_from_panel.side_effect=dispatch;f.snapshot.side_effect=snapshot
        f.confirm_returned_in_panel.side_effect=confirm
        with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
            result=run(Mock(),SimpleNamespace(parameters={'rally_count':4,'rally_queues':[1,2]}))
        self.assertEqual([('dispatch',1),('dispatch',2),('confirmed',1),('confirmed',2)]*2,events)
        self.assertEqual(8,f.panel.call_count)
        self.assertIn('4 次',result)

    def test_return_recheck_failure_is_bounded(self):
        import itertools
        f,events=self.scheduler_flow()
        def snapshot():
            for h in f.active.values():
                if not h.tracker.fought:h.tracker.observe(visible=True,status=S.FIGHTING,reliable=True)
                else:h.tracker.observe(visible=False,status=None,reliable=True,count_decreased=True)
            return True,[],0
        f.snapshot.side_effect=snapshot;f.confirm_returned_in_panel.return_value=False
        with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f), patch('agent.custom.action.auto_ling_er.time.monotonic',side_effect=itertools.count(0,2)):
            with self.assertRaisesRegex(RuntimeError,'连续三次返回复核失败'):
                run(Mock(),SimpleNamespace(parameters={'rally_count':2}))
        self.assertEqual(3,f.confirm_returned_in_panel.call_count)
        self.assertEqual(1,f.dispatch.call_count)

    def test_live_short_outbound_without_combat_recovers_and_reuses_queue(self):
        f,events=self.scheduler_flow()
        def snapshot():
            for h in f.active.values():
                if not h.tracker.departed:
                    h.tracker.observe(visible=True,status=S.OUTBOUND,reliable=True)
                else:h.tracker.observe(visible=False,status=None,reliable=True,count_decreased=True)
            return True,[],0
        f.snapshot.side_effect=snapshot
        f.confirm_returned_in_panel.return_value=True
        with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
            run(Mock(),SimpleNamespace(parameters={'rally_count':3,'rally_queues':[1,2]}))
        self.assertEqual([('dispatch',1),('dispatch',2),('dispatch',1)],events)
        self.assertEqual(3,f.confirm_returned_in_panel.call_count)

    def test_panel_animation_retries_recognition_only(self):
        f=LingEr.__new__(LingEr);f.pause=Mock();f.screenshot=Mock(return_value='settled')
        with patch.object(March,'panel',side_effect=[RuntimeError('无法唯一识别出征面板气泡指向'),(2,[])]) as panel:
            self.assertEqual((2,[]),f.panel('animating'))
        self.assertEqual(2,panel.call_count)
        f.screenshot.assert_called_once()
        with patch.object(March,'panel',side_effect=RuntimeError('队列区域超出截图')) as panel:
            with self.assertRaisesRegex(RuntimeError,'队列区域超出'):f.panel('bad')
            self.assertEqual(1,panel.call_count)
        with patch.object(March,'panel',side_effect=RuntimeError('气泡未出现')) as panel:
            with self.assertRaisesRegex(RuntimeError,'气泡'):f.panel('bad')
            self.assertEqual(4,panel.call_count)

    def test_successful_recheck_keeps_panel_and_baseline_for_multiple_queues(self):
        f,avatar=self.flow()
        old_row=SquadRow(np.random.default_rng(88).random((24,24,3)),S.OUTBOUND)
        f.snapshot.return_value=(True,[old_row],1)
        f.locate=Mock();f.text_button=Mock(return_value=True);f.close_dispatch_panel=Mock()
        for q in (1,2):
            h=MarchHandle(q,avatar,RallyTracker(departed=True,missing_after_departure=3),panel_avatar=avatar)
            self.assertTrue(f.confirm_returned_in_panel(h,keep_open=True))
        self.assertTrue(f.return_panel_open)
        self.assertEqual([old_row],f.return_panel_rows)
        self.assertTrue(f.pre_snapshot_reliable)
        f.snapshot.assert_called_once()
        f.locate.assert_called_once()
        f.text_button.assert_called_once_with('进攻')
        f.close_dispatch_panel.assert_not_called()

    def test_failed_kept_panel_recheck_closes_without_reopening(self):
        f,avatar=self.flow()
        f.return_panel_open=True;f.return_panel_rows=[]
        f.panel_busy[0]=True;f.locate=Mock();f.close_dispatch_panel=Mock()
        h=MarchHandle(1,avatar,RallyTracker(departed=True,missing_after_departure=3),panel_avatar=avatar)
        self.assertFalse(f.confirm_returned_in_panel(h,keep_open=True))
        self.assertFalse(f.return_panel_open)
        self.assertIsNone(f.return_panel_rows)
        f.locate.assert_not_called()
        f.close_dispatch_panel.assert_called_once()

    def test_loop_resumes_kept_panel_and_closes_at_final_budget(self):
        f,events=self.scheduler_flow()
        dispatch=f.dispatch.side_effect
        old_row=SquadRow(np.random.default_rng(444).random((24,24,3)),S.OUTBOUND)
        def snapshot():
            for h in f.active.values():
                if not h.tracker.departed:h.tracker.observe(visible=True,status=S.OUTBOUND,reliable=True)
                else:h.tracker.observe(visible=False,status=None,reliable=True,count_decreased=True)
            return True,[old_row],1
        def confirm(h,*,keep_open):
            self.assertTrue(keep_open)
            f.return_panel_open=True;f.return_panel_rows=[old_row]
            return True
        def resume(*,queue,existing):
            self.assertEqual([old_row],existing)
            self.assertFalse(f.active)  # Previous rally was counted and released first.
            f.close_dispatch_panel.assert_not_called()
            return dispatch(queue=queue)
        f.snapshot.side_effect=snapshot;f.confirm_returned_in_panel.side_effect=confirm
        f.dispatch_from_panel.side_effect=resume
        with patch('agent.custom.action.auto_ling_er.LingEr',return_value=f):
            result=run(Mock(),SimpleNamespace(parameters={'rally_count':2,'rally_queues':[2]}))
        self.assertEqual([('dispatch',2),('dispatch',2)],events)
        f.dispatch.assert_called_once()
        f.dispatch_from_panel.assert_called_once()
        f.close_dispatch_panel.assert_called_once()  # Only after the final completion.
        self.assertIn('2 次',result)

    def test_missed_departure_return_requires_two_idle_panel_reads(self):
        f, avatar = self.flow()
        f.locate = Mock(); f.text_button = Mock(return_value=True); f.close_dispatch_panel = Mock()
        tracker = RallyTracker(assembled=True)
        tracker.observe(visible=True, status=S.RETURNING, reliable=True)
        for _ in range(3):
            self.assertFalse(tracker.observe(visible=False, status=None, reliable=True, count_decreased=True))
        self.assertFalse(tracker.departed)
        self.assertTrue(tracker.ready_for_return_check)
        handle = MarchHandle(1, avatar, tracker, panel_avatar=avatar.copy())
        self.assertTrue(f.confirm_returned_in_panel(handle))
        self.assertEqual(2, f.panel.call_count)
        f.text_button.assert_called_once_with('进攻')
        f.panel_busy[0] = True
        self.assertFalse(f.confirm_returned_in_panel(handle))
        tracker.observe(visible=False, status=None, reliable=False)
        self.assertFalse(tracker.ready_for_return_check)

    def test_three_rallies_finish_when_first_departure_was_hidden(self):
        f, events = self.scheduler_flow()
        original_snapshot = f.snapshot.side_effect
        def snapshot():
            first = f.active.get(1)
            if first is not None and not getattr(first, 'missed_departure', False):
                first.missed_departure = True
                first.tracker.observe(visible=True, status=S.RETURNING, reliable=True)
            if first is not None:
                saved = f.active.pop(1)
                original_snapshot()
                f.active[1] = saved
                first.tracker.observe(visible=False, status=None, reliable=True, count_decreased=True)
            else:
                original_snapshot()
            self.assertLess(f.snapshot.call_count, 35, 'Returned squad must not stall the final budget')
            return True, [], 0
        def confirm(handle, **kwargs):
            self.assertTrue(handle.tracker.ready_for_return_check)
            self.assertFalse(handle.tracker.departed)
            return True
        f.snapshot.side_effect = snapshot
        f.confirm_returned_in_panel.side_effect = confirm
        with patch('agent.custom.action.auto_ling_er.LingEr', return_value=f):
            result = run(Mock(), SimpleNamespace(parameters={'rally_count': 3, 'rally_queues': [1, 2]}))
        self.assertEqual(3, sum(kind == 'dispatch' for kind, _ in events))
        self.assertFalse(f.active)
        self.assertIn('3 次', result)
        self.assertGreaterEqual(f.confirm_returned_in_panel.call_count, 1)

    def test_unreadable_list_stops_without_counting_or_dispatching(self):
        import itertools
        f, events = self.scheduler_flow()
        f.snapshot.return_value = (False, [], 0)
        f.snapshot.side_effect = None
        f.snapshot_reason = '当前不是大地图'
        with patch('agent.custom.action.auto_ling_er.LingEr', return_value=f), patch(
                'agent.custom.action.auto_ling_er.time.monotonic', side_effect=itertools.count(0, 10)):
            with self.assertRaisesRegex(RuntimeError, '连续 30 秒.*已完成 0/3'):
                run(Mock(), SimpleNamespace(parameters={'rally_count': 3}))
        f.dispatch.assert_not_called()
        f.confirm_returned_in_panel.assert_not_called()

    def test_known_portrait_updates_from_partial_rows_but_missing_requires_full_list(self):
        f,a=self.flow()
        h=MarchHandle(1,a,RallyTracker(state=S.ASSEMBLING,assembled=True))
        f.active={1:h}
        f.snapshot_rows_reliable=True
        for status in (S.OUTBOUND,S.RETURNING):
            f.observe_active(False,[SquadRow(a,status)])
            self.assertEqual(status,h.tracker.state)
        for _ in range(4):f.observe_active(False,[])
        self.assertEqual(S.RETURNING,h.tracker.state)
        self.assertEqual(0,h.tracker.missing)
        for _ in range(3):f.observe_active(True,[])
        self.assertEqual(S.COMPLETED,h.tracker.state)

    def test_untrusted_partial_rows_do_not_advance_state(self):
        f,a=self.flow()
        h=MarchHandle(1,a,RallyTracker(state=S.ASSEMBLING,assembled=True))
        f.active={1:h}
        f.snapshot_rows_reliable=False
        f.observe_active(False,[SquadRow(a,S.OUTBOUND)])
        self.assertEqual(S.ASSEMBLING,h.tracker.state)
        f.snapshot_rows_reliable=True
        f.observe_active(False,[SquadRow(a,S.OUTBOUND),SquadRow(a,S.OUTBOUND)])
        self.assertEqual(S.ASSEMBLING,h.tracker.state)

    def test_parameter_chain_and_defaults(self):
        for bad in (0,-1,100,True,'1.5',None):
            with self.assertRaises(ValueError):rally_level(bad)
        raw=json.dumps({'case_id':'auto_ling_er','rally_level':2,'rally_count':3})
        opts=parse_rally_options(raw)
        self.assertEqual({'rally_level':2,'rally_count':3},opts)
        self.assertEqual(['--rally-level','2','--rally-count','3'],worker_command_with_options('auto_ling_er',True,**opts)[-4:])
        with self.assertRaises(ValueError):parse_rally_options(raw.replace('auto_ling_er','auto_pixiu'))
        settings=generate()['option']['玲儿集结设置']
        self.assertEqual(['1','1'],[i['default'] for i in settings['inputs']])

    def test_native_screenshots(self):
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('ling_er_native_probe.py'))],capture_output=True,text=True,encoding='utf-8',timeout=90)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
