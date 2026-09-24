# Native regression in a subprocess: other tests switch Maa to AgentServer globally.
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maa.resource import Resource
from maa.tasker import Tasker
from maa.library import Library
from agent.recognition_fallback import apply_full_image_fallbacks
from agent.custom.action.march.march import March, MarchHandle, similarity
from agent.custom.action.march.state import MarchState, MarchTracker, parse_status

def main():
    root=Path(__file__).resolve().parents[1]
    resource=Resource()
    assert resource.post_bundle(root/'resource/base').wait().succeeded
    apply_full_image_fallbacks(resource)
    tasker=Tasker()
    assert Library.framework().MaaTaskerBindResource(tasker._handle,resource._handle)
    flow=March.__new__(March);flow.tasker=tasker
    flow.engine=SimpleNamespace(stop_event=threading.Event(),_state_lock=threading.RLock(),_current_tasker=None)
    with np.load(root/'tests/data/march_other_user.npz') as images:
        actual, slots = flow.panel(images['panel'])
        assert actual == 1, actual
        assert [slot[0] for slot in slots] == [True, True, False, True]
        assert flow.panel_busy == [False, False, False, False]
    with np.load(root/'tests/data/march_screens.npz') as images:
        for name,selected,unlocked in [('panel1',1,[True,False,False,False]),('panel2',2,[True,True,False,False])]:
            actual,slots=flow.panel(images[name])
            assert actual==selected,(name,actual)
            assert [s[0] for s in slots]==unlocked,(name,slots)
        for name,count in [('one',1),('two',2)]:
            flow.screenshot=lambda:images[name]
            valid,rows,actual=flow.snapshot()
            assert valid and actual==count,(name,valid,actual)
            assert all(row.status==MarchState.OUTBOUND for row in rows),rows
        _,slots=flow.panel(images['panel2'])
        assert similarity(slots[0][2],rows[0].avatar)>=.72
        assert similarity(slots[1][2],rows[1].avatar)>=.72
        assert similarity(slots[0][2],rows[1].avatar)<.65
        assert similarity(slots[1][2],rows[0].avatar)<.65
        flow.screenshot=lambda:images['empty_world']
        assert flow.snapshot()==(True, [], 0), "Empty list must require world confirmation"
        flow.screenshot=lambda:np.zeros_like(images['empty_world'])
        assert flow.snapshot()==(False, [], 0), "Hidden UI is not completion"
        collapsed=images['two'].copy()
        collapsed[420:]=0
        flow.screenshot=lambda:collapsed
        assert not flow.snapshot()[0], "Collapsed list is not completion"
        for name,state in [('returning',MarchState.RETURNING),('fighting',MarchState.FIGHTING)]:
            # These are user-provided row snippets; exclude timer below y=31.
            texts=flow.ocr(images[name][3:31,55:197],only_rec=True)
            assert any(parse_status(r.text)==state for r in texts),(name,[r.text for r in texts])
        for name,label in [('attack_monster','进攻'),('attack_city','进攻'),('panel1','出征'),('panel2','出征'),('auto_deploy','一键上阵')]:
            flow.screenshot=lambda:images[name]
            clicks=[]
            flow.click=lambda *point:clicks.append(point)
            flow.pause=lambda seconds:None
            assert flow.text_button(label,timeout=2),(name,label)
            assert len(clicks)==1
            if label=='进攻':
                image=images[name]; y0=int(image.shape[0]*.25)
                caption=flow.ocr(image[y0:int(image.shape[0]*.86)], ['^进攻$'])[0].box
                assert clicks[0][1] < y0+caption.y, 'Click icon, not caption' 
    with np.load(root/'tests/data/march_live.npz') as images:
        selected, slots=flow.panel(images['panel'])
        assert selected==1 and slots[0][0]
        flow.engine.log=lambda message:None
        handle=MarchHandle(selected,slots[0][2],MarchTracker())
        for name,state in [('outbound',MarchState.OUTBOUND),('fighting',MarchState.FIGHTING),('returning',MarchState.RETURNING)]:
            flow.screenshot=lambda:images[name]
            valid,rows,count=flow.snapshot()
            assert valid and count==1 and rows[0].status==state,(name,valid,count,rows)
            assert similarity(rows[0].avatar,handle.avatar)>=.72
            assert not flow.poll(handle)
            assert handle.tracker.state==state
        flow.screenshot=lambda:images['ended']
        assert [flow.poll(handle) for _ in range(3)]==[False,False,True]
    with np.load(root/'tests/data/march_gathering.npz') as images:
        flow.screenshot=lambda:images['world']
        valid, rows, count = flow.snapshot()
        assert valid and count == 2 and len(rows) == 2, ('gathering', valid, count, len(rows))
        assert rows[0].status is None  # Gathering is occupied, not a battle lifecycle state.
        assert rows[1].status == MarchState.RETURNING
    with np.load(root/'tests/data/pixiu_zero.npz') as images:
        flow.panel(images['panel'])
        assert flow.panel_busy == [True, True, False, False], ('busy panels', flow.panel_busy)
    print('March native screenshot recognition: PASS')

if __name__=='__main__':
    main()
