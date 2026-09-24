import sys
import threading
from pathlib import Path
from types import SimpleNamespace
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maa.resource import Resource
from maa.tasker import Tasker
from maa.library import Library
from agent.custom.action.auto_ling_er import LingEr
from agent.custom.action.march.state import MarchState, parse_status
root=Path(__file__).resolve().parents[1]
resource=Resource()
assert resource.post_bundle(root/'resource/base').wait().succeeded
tasker=Tasker()
assert Library.framework().MaaTaskerBindResource(tasker._handle, resource._handle)
f=LingEr.__new__(LingEr);f.tasker=tasker
f.engine=SimpleNamespace(stop_event=threading.Event(),_state_lock=threading.RLock(),_current_tasker=None,log=print)
f.click=lambda *p: print('click',p)
f.pause=lambda seconds: None
with np.load(root/'tests/data/ling_er.npz') as images:
 for name in images.files:
  f.screenshot=lambda:images[name]
  if name=='boss':
   assert f.search_level()==4
   assert f.region_text('^兽潮首领$',(.62,.53,1,.61))
   assert f.region_text('^搜索$',(.26,.89,.73,.98))
   assert f.icon_button('plus',(.78,.84,.94,.91),timeout=2)
   assert f.icon_button('minus',(.06,.84,.22,.91),timeout=2)
  elif name=='target':
   assert f.region_text(r'^等级\s*4\s*妖兽洞穴$',(.1,.25,.9,.65))
   assert f.text_button('进攻',timeout=2)
  elif name=='panel':
   selected,slots=f.panel(images[name]);print('panel',selected,[s[0] for s in slots],f.panel_busy)
   assert selected==1 and slots[0][0] and not f.panel_busy[0]
   assert not f.zero_disciples()
   assert f.text_button('出征',timeout=2)
  elif name=='assembling':
   valid,rows,count=f.snapshot();print('snapshot',valid,count,[r.status for r in rows])
   assert valid and count==1 and rows[0].status==MarchState.ASSEMBLING
  elif name=='world':
   assert f.icon_button('search',(0,.70,.16,.84),timeout=2)
# Reproduce the logged failure branch: the translucent header template misses,
# while the actual 小队 text, count and row icons are still visible.
original_templates = f.templates
f.templates = lambda image, name, threshold=.72: [] if name == 'header' else original_templates(image, name, threshold)
with np.load(root/'tests/data/ling_er.npz') as images:
 f.screenshot=lambda: images['assembling']
 valid,rows,count=f.snapshot()
 assert valid and count==1 and rows[0].status==MarchState.ASSEMBLING, (valid,count,rows)
with np.load(root/'tests/data/ling_er_header_live.npz') as images:
 f.screenshot=lambda: images['world']
 assert f.snapshot()==(True,[],0), 'Live zero count header must remain readable through background map labels'
for archive, names in [('march_live.npz', ['outbound','fighting','returning']), ('march_screens.npz', ['one','two'])]:
 with np.load(root/'tests/data'/archive) as images:
  for name in names:
   f.screenshot=lambda:images[name]
   valid,rows,count=f.snapshot()
   assert valid and count>0 and len(rows)==count,(archive,name,valid,count)
   assert all(row.status is not None for row in rows),(name,rows)
f.screenshot=lambda: np.zeros((1298,720,3),dtype=np.uint8)
assert not f.snapshot()[0], 'Blank/hidden UI must not be treated as a completed return'
with np.load(root/'tests/data/ling_er_assembling_row.npz') as images:
 row=images['row']
 texts=f.ocr(row[:35,58:215],only_rec=True)
 assert len(texts)==1 and parse_status(texts[0].text)==MarchState.ASSEMBLING, [t.text for t in texts]
 assert len(f.row_anchors(row))==1, 'User-provided assembling eye button must anchor one squad row'
 timer=f.ocr(row[38:60,70:195],only_rec=True)
 assert all(parse_status(t.text) is None for t in timer), 'Countdown is not a squad status'
# A false header over a map label used to read 盟友 instead of the count.
from maa.define import Rect
f.templates = lambda image, name, threshold=.72: [SimpleNamespace(box=Rect(0,0,51,32))] if name == 'header' else original_templates(image, name, threshold)
with np.load(root/'tests/data/ling_er.npz') as images:
 f.screenshot=lambda: images['assembling']
 valid,rows,count=f.snapshot()
 assert valid and count==1 and rows[0].status==MarchState.ASSEMBLING, (valid,count,rows)
# Count text can be covered by a map label while squad states remain legible.
f.templates = original_templates
original_ocr = f.ocr
def unreadable_count(image, expected=None, only_rec=False):
 if expected == [r"[0-4][/／][1-4]"]:
  return []
 return original_ocr(image, expected, only_rec)
f.ocr = unreadable_count
with np.load(root/'tests/data/march_live.npz') as images:
 for name,status in [('outbound',MarchState.OUTBOUND),('returning',MarchState.RETURNING)]:
  f.screenshot=lambda:images[name]
  valid,rows,count=f.snapshot()
  assert not valid and f.snapshot_rows_reliable and len(rows)==1,(name,valid,count,rows)
  assert rows[0].status==status,(name,rows)
f.ocr = original_ocr
# Reproduce an OCR strip polluted by a background map name; verify the
# shortened crop actually recognizes the label using native OCR.
def noisy_wide_strip(image, expected=None, only_rec=False):
 results=original_ocr(image,expected,only_rec)
 if only_rec and image.shape[1]>120 and image.shape[0]<40:
  for r in results:
   if parse_status(r.text) in (MarchState.ASSEMBLING,MarchState.RETURNING,MarchState.FIGHTING):
    r.text += '·魂]掌门10'
 return results
f.ocr = noisy_wide_strip
with np.load(root/'tests/data/ling_er.npz') as images:
 f.screenshot=lambda:images['assembling']
 valid,rows,count=f.snapshot()
 assert valid and rows[0].status==MarchState.ASSEMBLING,(valid,rows,f.snapshot_status_texts)
 assert len(f.snapshot_status_texts[0])>=2
f.ocr = original_ocr
print('LingEr native screenshot checks passed')
