import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maa.resource import Resource
from maa.tasker import Tasker
from maa.library import Library
from agent.custom.action.auto_pixiu import Pixiu

root = Path(__file__).resolve().parents[1]
r = Resource()
assert r.post_bundle(root / 'resource/base').wait().succeeded
t = Tasker()
assert Library.framework().MaaTaskerBindResource(t._handle, r._handle)
f = Pixiu.__new__(Pixiu)
f.tasker = t
f.engine = SimpleNamespace(stop_event=threading.Event(), _state_lock=threading.RLock(), _current_tasker=None, log=print)
frames = np.load(root/'tests/data/pixiu_entry.npz')
world, activity, pixiu = (frames[name] for name in ('world','activity','pixiu'))
for name, frame, expected in [('world', world, False), ('activity', activity, True), ('pixiu', pixiu, True)]:
    f.screenshot = lambda: frame
    actual = f.activity_visible()
    print(name, actual)
    assert actual == expected, name
clicks = []
f.screenshot = lambda: activity if clicks else world
f.click = lambda x,y: clicks.append((x,y))
f.pause = lambda seconds: None
f.open_activity()
assert len(clicks) == 1 and 637 <= clicks[0][0] <= 687 and 265 <= clicks[0][1] <= 299, clicks
print('OFFLINE icon click / activity gating: PASS', clicks)

with np.load(root/'tests/data/pixiu_zero.npz') as zero:
    f.screenshot = lambda: zero['panel']
    assert f.zero_disciples(), 'User screenshot 0/0 must prevent dispatch'
with np.load(root/'tests/data/march_screens.npz') as march:
    f.screenshot = lambda: march['panel1']
    assert not f.zero_disciples(), 'Nonzero disciples must remain dispatchable'
print('OFFLINE disciple count: PASS')
