"""Selected-squad Ling'er rallies, counted only after the full return lifecycle."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from maa.pipeline import JRecognitionType, JTemplateMatch
from agent.custom.action.auto_pixiu import Pixiu, NoFreeQueue, ZeroDisciples, attack_count
from agent.custom.action.march.march import March, similarity
from agent.custom.action.march.state import MarchState as S, MarchTracker


def rally_level(value):
    if isinstance(value, bool) or not re.fullmatch(r"[1-9]\d?", str(value)):
        raise ValueError("集结等级必须为 1–99 的整数；实际可选等级以游戏为准")
    return int(value)


def rally_queues(value):
    if isinstance(value, str):
        if not re.fullmatch(r"[1-4](?:,[1-4])*", value):
            raise ValueError("请至少勾选一个集结队列（1、2、3、4）")
        value = [int(item) for item in value.split(',')]
    if (not isinstance(value, (list, tuple)) or not value
            or any(type(item) is not int or item not in range(1, 5) for item in value)
            or len(set(value)) != len(value)):
        raise ValueError("集结队列必须为 1、2、3、4 中至少一个不重复的队号")
    return sorted(value)


@dataclass
class RallyTracker(MarchTracker):
    assembled: bool = False
    departed: bool = False
    fought: bool = False
    missing_after_departure: int = 0
    missing_observations: int = 0

    @property
    def ready_for_return_check(self):
        # Dispatching another squad can hide the short outbound/combat phase.
        # An observed return is sufficient to request inspection, never to count
        # completion by itself: the saved squad must be idle on two panel reads.
        return ((self.departed and self.missing_after_departure >= 3)
                or (self.assembled and self.state == S.RETURNING
                    and self.missing_observations >= 3))

    def observe(self, *, visible, status, reliable, count_decreased=False):
        if reliable and visible:
            if status == S.ASSEMBLING:
                self.assembled = True
            if self.assembled and status in (S.OUTBOUND, S.FIGHTING):
                self.departed = True
            if self.assembled and status == S.FIGHTING:
                self.fought = True
        self.missing_observations = (self.missing_observations + 1 if reliable and not visible else 0)
        self.missing_after_departure = (self.missing_after_departure + 1
                                     if reliable and not visible and self.departed else 0)
        return super().observe(visible=visible, status=status, reliable=reliable,
                               count_decreased=count_decreased and self.assembled and self.departed)


class LingEr(Pixiu):
    def panel(self, image):
        # The rally popup animates into place. Retry recognition only, never the
        # rally/submit click, while its pointer is not yet fully visible.
        for attempt in range(4):
            try:
                return super().panel(image)
            except RuntimeError as exc:
                if '气泡' not in str(exc) or attempt == 3:
                    raise
                self.pause(.35)
                image = self.screenshot()

    def asset(self, image, name):
        result = self.recognize(image.copy(), JRecognitionType.TemplateMatch,
                               JTemplateMatch(template=[f"AutoLingEr/{name}.png"], threshold=[.75]))
        return result.filtered_results if result.hit else []

    def row_anchors(self, image):
        anchors = super().row_anchors(image)
        for candidate in self.asset(image, "assembling"):
            if not any(abs(candidate.box.y - a.box.y) < 15 and
                       abs(candidate.box.x - a.box.x) < 15 for a in anchors):
                anchors.append(candidate)
        return sorted(anchors, key=lambda item: item.box.y)

    def icon_button(self, name, region, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            image = self.screenshot()
            h, w = image.shape[:2]
            x0, y0, x1, y1 = [int(v * s) for v, s in zip(region, (w, h, w, h))]
            hits = self.asset(image[y0:y1, x0:x1], name)
            if len(hits) == 1:
                box = hits[0].box
                self.click(x0 + box.x + box.w / 2, y0 + box.y + box.h / 2)
                self.pause(.5)
                return True
            self.pause(.2)
        return False

    def search_level(self):
        image = self.screenshot()
        h, w = image.shape[:2]
        # Confirm boss content and read only the level above the slider.
        if not self.ocr(image[int(h*.58):int(h*.72)], ['^妖兽洞穴$']):
            raise RuntimeError("未确认兽潮首领的妖兽洞穴，停止调整等级")
        hits = self.ocr(image[int(h*.82):int(h*.865), int(w*.38):int(w*.62)], [r'^\d+级$'])
        if len(hits) != 1:
            raise RuntimeError("无法唯一识别搜索等级，未点击搜索")
        return int(re.fullmatch(r'(\d+)级', hits[0].text.strip())[1])

    def adjust_level(self, target):
        current = self.search_level()
        for _ in range(100):
            if current == target:
                self.pause(.3)
                if self.search_level() == target:
                    return
                raise RuntimeError("等级复核不一致，未点击搜索")
            direction = 1 if current < target else -1
            if not self.icon_button('plus' if direction > 0 else 'minus', (.78, .84, .94, .91) if direction > 0 else (.06, .84, .22, .91)):
                raise RuntimeError("未唯一识别等级加减按钮")
            after = self.search_level()
            if after != current + direction:
                raise RuntimeError("等级调整未生效或已到游戏等级边界，未点击搜索")
            current = after
        raise RuntimeError("等级调整超过上限")

    def locate(self, _engine):
        if not self.icon_button('search', (0, .70, .16, .84)):
            raise RuntimeError("未找到大地图左下角搜索图标")
        if not self.region_text('^兽潮首领$', (.62, .53, 1, .61), click=True):
            raise RuntimeError("未找到兽潮首领页签")
        self.adjust_level(self.level)
        if not self.region_text('^搜索$', (.26, .89, .73, .98), click=True):
            raise RuntimeError("未找到底部搜索按钮")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.region_text(rf'^等级\s*{self.level}\s*妖兽洞穴$', (.1, .25, .9, .65)):
                return
            self.pause(.3)
        raise RuntimeError("搜索后未确认指定等级妖兽洞穴，未集结")

    def text_button(self, text, timeout=8):
        if text == '进攻':
            return self.icon_button('rally', (.15, .45, .85, .87), timeout)
        if text == '出征':
            if self.zero_disciples():
                raise ZeroDisciples("所选队列弟子数量为 0，未点击组队")
            return March.text_button(self, '组队', timeout)
        return March.text_button(self, text, timeout)

    def dispatch_from_panel(self, queue=None, *, existing=None, timeout=15):
        allowed = getattr(self, 'allowed_queues', [1])
        queue = allowed[0] if queue is None else queue
        if queue not in allowed:
            raise ValueError(f"第 {queue} 队未勾选，不参与集结")
        if queue in getattr(self, 'active', {}):
            raise NoFreeQueue(f"第 {queue} 队仍在跟踪中，不能重复派遣")
        existing = existing or []
        for _ in range(2):
            _, slots = self.panel(self.screenshot())
            if not slots[queue - 1][0]:
                raise RuntimeError(f"第 {queue} 队未解锁或队号识别失败")
            avatar = slots[queue - 1][2]
            if self.panel_busy[queue - 1] or any(similarity(row.avatar, avatar) >= .65 for row in existing):
                if not hasattr(self, 'blocked'):
                    self.blocked = {}
                self.blocked[queue] = (avatar, 0)
                raise NoFreeQueue(f"第 {queue} 队正在占用，等待返回")
            self.pause(.35)
        try:
            handle = March.dispatch_from_panel(self, queue, existing=existing, timeout=timeout)
        except ZeroDisciples:
            raise
        except (RuntimeError, TimeoutError):
            # Only an explicit blocked-stamina prompt permits retrying submission.
            if not self.pipeline('通用识别补充体力按钮'):
                raise
            if not self.engine.auto_stamina:
                raise RuntimeError('体力不足，未勾选自动补体')
            if not self.engine._try_auto_stamina(self.tasker):
                raise RuntimeError('自动补体未成功或没有可用体力来源')
            handle = March.dispatch_from_panel(self, queue, existing=existing, timeout=timeout)
        if handle.tracker.state != S.ASSEMBLING:
            raise RuntimeError('已点击组队，但未确认集结中状态；停止以防重复集结')
        handle.tracker = RallyTracker(state=S.ASSEMBLING, assembled=True)
        return handle

    def confirm_returned_in_panel(self, handle, *, keep_open=False):
        """Read-only squad inspection when brief travel/return frames were missed."""
        if not handle.tracker.ready_for_return_check:
            return False
        if handle.panel_avatar is None:
            raise RuntimeError(f'第 {handle.queue} 队缺少派遣前的面板头像，无法安全复核')
        self.engine.log(f"第 {handle.queue} 队行军后连续消失，复核组队面板是否已返回空闲")
        if getattr(self, 'return_panel_open', False) is not True:
            # Preserve a reliable HUD baseline before the panel hides it. The
            # common dispatch confirmation needs this to identify an added row.
            self.return_panel_rows = March.pre_dispatch_rows(self)
            self.locate(self.engine)
            if not self.text_button('进攻'):
                raise RuntimeError('无法打开集结面板复核返回状态，未计数、未再次组队')
            self.return_panel_open = True
        confirmed = False
        try:
            self.pause(.6)
            for _ in range(2):
                _, slots = self.panel(self.screenshot())
                unlocked, _, avatar = slots[handle.queue - 1]
                score = similarity(avatar, handle.panel_avatar)
                busy = self.panel_busy[handle.queue - 1]
                self.engine.log(f'第 {handle.queue} 队返回复核：队号可用={unlocked}，占用={busy}，面板头像相似度={score:.3f}')
                if not unlocked or busy or score < .80:
                    return False
                self.pause(.35)
            confirmed = True
            return True
        finally:
            if not confirmed or not keep_open:
                self.close_dispatch_panel()
                self.return_panel_open = False
                self.return_panel_rows = None

    def observe_active(self, valid, rows):
        # Every reliable HUD snapshot updates all owned squads, including frames
        # captured while confirming another squad's dispatch. Row order is irrelevant.
        active = getattr(self, 'active', {})
        matches = {q: [i for i, row in enumerate(rows) if similarity(row.avatar, h.avatar) >= .72]
                   for q, h in active.items() if h.tracker.state != S.COMPLETED}
        for q, indices in matches.items():
            handle = active[q]
            ambiguous = len(indices) > 1 or any(
                i in other for other_q, other in matches.items() if other_q != q for i in indices)
            previous = handle.tracker.state
            handle.tracker.observe(
                visible=bool(indices), status=rows[indices[0]].status if len(indices) == 1 else None,
                reliable=(valid or (getattr(self, 'snapshot_rows_reliable', False) is True
                                    and len(indices) == 1 and rows[indices[0]].status is not None))
                         and not ambiguous,
                # Other squads can be dispatched as this squad returns, keeping
                # the total count unchanged. A reliable full list and three
                # consecutive absences of this returning avatar prove completion.
                count_decreased=True,
            )
            if previous != handle.tracker.state:
                self.engine.log(f"第 {q} 队：{handle.tracker.state}")
        for q, (avatar, confirmations) in list(getattr(self, 'blocked', {}).items()):
            busy = any(similarity(row.avatar, avatar) >= .65 for row in rows)
            confirmations = confirmations + 1 if valid and not busy else 0
            if confirmations >= 3:
                del self.blocked[q]
            else:
                self.blocked[q] = (avatar, confirmations)

    def snapshot(self):
        valid, rows, count = super().snapshot()
        self.observe_active(valid, rows)
        if getattr(self, 'active', {}) and time.monotonic() >= getattr(self, '_next_snapshot_log', 0):
            self.engine.log(f"集结跟踪：列表可靠={valid}，占用={count}，状态={[row.status for row in rows]}，"
                            f"队列状态={[(q, h.tracker.state) for q, h in self.active.items()]}，"
                            f"状态原文={getattr(self, 'snapshot_status_texts', [])}，"
                            f"识别说明={getattr(self, 'snapshot_reason', '')}")
            self._next_snapshot_log = time.monotonic() + 10
        return valid, rows, count


def run(engine, case):
    params = case.parameters or {}
    level = rally_level(params.get('rally_level', 1))
    count = attack_count(params.get('rally_count', 1))
    queues = rally_queues(params.get('rally_queues', [1]))
    flow = LingEr(engine)
    flow.level = level
    flow.allowed_queues = queues
    flow.active = {}
    flow.blocked = {}
    flow.return_panel_open = False
    flow.return_panel_rows = None
    deadlines = {}
    next_return_check = {}
    return_check_failures = {}
    completed = 0
    cursor = 0
    idle_deadline = time.monotonic() + 3600
    if not flow.pipeline('通用行军进入大地图'):
        raise RuntimeError('无法进入大地图')
    unreliable_since = None
    while completed < count:
        valid, _, _ = flow.snapshot()
        if not valid:
            now = time.monotonic()
            if unreliable_since is None:
                unreliable_since = now
            elif now - unreliable_since >= 30:
                raise RuntimeError(f'连续 30 秒无法可靠识别小队列表；已完成 {completed}/{count} 次；'
                                   f'识别说明：{flow.snapshot_reason}。请回到大地图后重试')
            flow.pause(.5)
            continue
        unreliable_since = None
        # Keep the HUD visible while any tracked squad is still active. Opening
        # search/panels repeatedly can hide another squad's brief combat phase.
        can_inspect_returns = all(h.tracker.state == S.COMPLETED or h.tracker.missing_observations >= 3
                                  for h in flow.active.values())
        for q, handle in list(flow.active.items()):
            if (handle.tracker.missing_observations >= 30 and not handle.tracker.departed
                    and handle.tracker.state != S.RETURNING and handle.tracker.state != S.COMPLETED):
                raise RuntimeError(f'第 {q} 队已连续消失 30 次，但未确认出发或返回；'
                                   '可能集结取消或状态识别异常，停止以避免长期空等和错误计数')
            if (handle.tracker.state != S.COMPLETED and handle.tracker.ready_for_return_check
                    and can_inspect_returns
                    and time.monotonic() >= next_return_check.get(q, 0)):
                next_return_check[q] = time.monotonic() + 10
                if flow.confirm_returned_in_panel(handle, keep_open=True):
                    handle.tracker.state = S.COMPLETED
                    engine.log(f'第 {q} 队：行军后消失，面板连续确认已返回空闲')
                else:
                    return_check_failures[q] = return_check_failures.get(q, 0) + 1
                    if return_check_failures[q] >= 3:
                        raise RuntimeError(f'第 {q} 队连续三次返回复核失败，停止重复开面板；请查看队号、占用和头像诊断')
            if handle.tracker.state == S.COMPLETED:
                completed += 1
                del flow.active[q]
                del deadlines[q]
                next_return_check.pop(q, None)
                return_check_failures.pop(q, None)
                idle_deadline = time.monotonic() + 3600
                engine.log(f'第 {q} 队集结完成；总进度 {completed}/{count}（已确认返回空闲）')
            elif time.monotonic() >= deadlines[q]:
                raise TimeoutError(f'第 {q} 队集结等待超时；已完成 {completed}/{count} 次')
        if completed >= count:
            if flow.return_panel_open:
                flow.close_dispatch_panel()
                flow.return_panel_open = False
            break
        if time.monotonic() >= idle_deadline:
            raise TimeoutError('等待勾选队列可用或集结完成超时')
        # Each in-flight rally reserves one of the remaining total attempts.
        # Round-robin prevents the lowest queue number from monopolizing work.
        candidates = [queues[(cursor + offset) % len(queues)] for offset in range(len(queues))]
        queue = next((q for q in candidates if q not in flow.active and q not in flow.blocked), None)
        pending_return = any(h.tracker.ready_for_return_check for h in flow.active.values())
        if completed + len(flow.active) < count and queue is not None and not pending_return:
            cursor = (queues.index(queue) + 1) % len(queues)
            try:
                if flow.return_panel_open:
                    engine.log(f'复用组队面板，直接派遣第 {queue} 队')
                    existing = flow.return_panel_rows
                    flow.return_panel_open = False
                    flow.return_panel_rows = None
                    handle = flow.dispatch_from_panel(queue=queue, existing=existing)
                else:
                    handle = flow.dispatch(None, queue=queue, select_target=flow.locate)
            except NoFreeQueue:
                flow.close_dispatch_panel()
                engine.log(f'第 {queue} 队占用，等待返回；继续检查其他勾选队列')
                continue
            except ZeroDisciples:
                flow.close_dispatch_panel()
                raise
            flow.active[queue] = handle
            deadlines[queue] = time.monotonic() + 3600
            continue
        if flow.return_panel_open:
            # No dispatch budget/free selected squad, or another return check
            # must wait. Restore HUD visibility instead of polling behind a panel.
            flow.close_dispatch_panel()
            flow.return_panel_open = False
            flow.return_panel_rows = None
        flow.pause(.5)
    return f'已完成 {count} 次玲儿降妖集结，等级 {level}，参与队列：{",".join(map(str, queues))}'
