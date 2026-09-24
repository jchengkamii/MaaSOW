"""Locate treasure pixiu through activity tabs and reuse the common march flow."""
from __future__ import annotations

import re
import time

from maa.pipeline import JRecognitionType, JTemplateMatch

from agent.custom.action.march.march import March, similarity


def attack_count(value):
    if isinstance(value, bool) or not re.fullmatch(r"[1-9]\d{0,3}|10000", str(value)):
        raise ValueError("进攻次数必须为 1–10000 的整数")
    return int(value)


class NoFreeQueue(RuntimeError):
    """Panel was inspected but no safe dispatch candidate was found."""


class ZeroDisciples(RuntimeError):
    """The selected squad has no disciples; no dispatch click was issued."""


class Pixiu(March):
    def pre_dispatch_rows(self):
        self.pre_snapshot_reliable = False
        # The panel's badge/bar checks remain authoritative when HUD OCR is
        # temporarily unreadable. Do not turn an unreadable frame into free slots.
        for attempt in range(3):
            valid, rows, _ = self.snapshot()
            if valid:
                self.pre_snapshot_reliable = True
                return rows
            if attempt < 2:
                self.pause(.3)
        self.engine.log("左上角队列连续识别不完整，改从出征面板检查各队占用状态")
        return []

    def zero_disciples(self):
        image = self.screenshot()
        h, w = image.shape[:2]
        top = int(h * .30)
        results = self.ocr(image[top:int(h * .65)])
        labels = [result for result in results if result.text.strip() == "弟子数量"]
        if len(labels) != 1:
            raise RuntimeError("无法确认出征面板弟子数量，未点击出征")
        box = labels[0].box
        # Read title and fraction from one sufficiently tall crop; narrow strips
        # can make the OCR detector miss white outlined digits.
        fragments = [result for result in results
                  if re.fullmatch(r"[\d\s/／]+", result.text.strip())
                  and box.y + box.h <= result.box.y <= box.y + box.h + 75 * w / 720
                  and abs(result.box.x + result.box.w / 2 - box.x - box.w / 2) < w * .2]
        # OCR can split 141/1047 into overlapping boxes "141" and "/1047".
        # Only join nearby fragments on the same line below the quantity title.
        groups = []
        for result in sorted(fragments, key=lambda item: item.box.x):
            for group in groups:
                previous = group[-1].box
                current = result.box
                same_line = abs(current.y + current.h / 2 - previous.y - previous.h / 2) <= min(current.h, previous.h) * .5
                gap = current.x - previous.x - previous.w
                if same_line and -10 * w / 720 <= gap <= 20 * w / 720:
                    group.append(result)
                    break
            else:
                groups.append([result])
        values = [re.sub(r"\s+", "", "".join(item.text for item in group)) for group in groups]
        values = [value for value in values if re.fullmatch(r"\d+[/／]\d+", value)]
        if len(values) != 1:
            raise RuntimeError("无法读取弟子数量数值，未点击出征")
        match = re.fullmatch(r"(\d+)[/／](\d+)", values[0])
        if match is None:
            raise RuntimeError("弟子数量格式无法确认，未点击出征")
        return int(match[1]) == 0

    def text_button(self, text, timeout=8):
        # Common march calls this after selecting the squad and auto-deploying.
        if text == "出征" and self.zero_disciples():
            raise ZeroDisciples("弟子数量为 0，等待队伍返回")
        return super().text_button(text, timeout=timeout)

    def close_dispatch_panel(self):
        image = self.screenshot()
        h, w = image.shape[:2]
        self.click(w * .12, h * .20)
        self.pause(.5)
        if not self.pipeline("通用行军进入大地图"):
            raise RuntimeError("点击空白关闭出征面板后未能返回大地图")

    def close_and_wait_for_return(self, occupied_before, deadline):
        self.close_dispatch_panel()
        if occupied_before <= 0:
            raise RuntimeError("弟子数量为 0，且没有正在外出的队伍可等待返回")
        self.engine.log("弟子数量为 0，已关闭面板；等待外出队伍返回后再试")
        confirmations = 0
        while time.monotonic() < deadline:
            valid, _, occupied = self.snapshot()
            confirmations = confirmations + 1 if valid and occupied < occupied_before else 0
            if confirmations >= 2:
                self.engine.log("已确认队列占用减少，继续定位貔貅")
                return
            self.pause(1)
        raise TimeoutError("弟子数量为 0，等待队伍返回超时；本次未出征、未计数")

    def activity_visible(self):
        image = self.screenshot()
        h, w = image.shape[:2]
        back = self.recognize(
            image[int(h * .88):, :int(w * .18)].copy(),
            JRecognitionType.TemplateMatch,
            JTemplateMatch(template=["AutoPixiu/activity_back.png", "AutoRadar/return_blue_reference.png",
                                     "AutoRadar/return_blue_runtime.png"], threshold=[.68]),
        )
        # Require both the activity carousel and its back button on one frame.
        if not back.hit:
            return False
        labels = self.ocr(image[int(h * .95):, int(w * .18):])
        return any(re.fullmatch(r"[\u4e00-\u9fff]{3,8}", label.text.strip()) for label in labels)

    def open_activity(self):
        image = self.screenshot()
        h, w = image.shape[:2]
        left, top = int(w * .78), int(h * .1)
        roi = image[top:int(h * .4), left:]
        labels = self.ocr(roi, ["^玩法活动$"])
        if len(labels) != 1:
            raise RuntimeError("未找到右上角玩法活动入口")
        label = labels[0].box
        # OCR anchors the search area; the icon match supplies the actual click.
        x0 = max(0, int(label.x - 12 * w / 720))
        y0 = max(0, int(label.y - 90 * w / 720))
        x1 = min(roi.shape[1], int(label.x + label.w + 12 * w / 720))
        icons = self.recognize(
            roi[y0:label.y, x0:x1].copy(), JRecognitionType.TemplateMatch,
            JTemplateMatch(template=["AutoPixiu/activity_icon.png"], threshold=[.78]),
        )
        if not icons.hit or len(icons.filtered_results) != 1:
            raise RuntimeError("找到玩法活动文字，但未唯一识别到上方图标，未点击")
        box = icons.filtered_results[0].box
        x, y = left + x0 + box.x + box.w / 2, top + y0 + box.y + box.h / 2
        self.engine.log(f"玩法活动图标定位：截图 {w}x{h}，点击 ({int(x)}, {int(y)})")
        self.click(x, y)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.pause(.3)
            if self.activity_visible():
                return
        raise RuntimeError("点击玩法活动图标后未确认活动界面，已停止，未滑动")

    def region_text(self, pattern, region, click=False):
        image = self.screenshot()
        h, w = image.shape[:2]
        x0, y0, x1, y1 = [int(v * s) for v, s in zip(region, (w, h, w, h))]
        hits = self.ocr(image[y0:y1, x0:x1], [pattern])
        if len(hits) != 1:
            return False
        if click:
            box = hits[0].box
            self.click(x0 + box.x + box.w / 2, y0 + box.y + box.h / 2)
            self.pause(.7)
        return True

    def swipe_tabs(self, left):
        if not self.activity_visible():
            raise RuntimeError("未确认活动页签栏，已停止滑动")
        image = self.screenshot()
        h, w = image.shape[:2]
        begin, end = (.88, .30) if left else (.30, .88)
        if not self.controller.post_swipe(int(w * begin), int(h * .945),
                                          int(w * end), int(h * .945), 450).wait().succeeded:
            raise RuntimeError("滑动活动页签失败")
        self.pause(.6)

    def tab_signature(self):
        image = self.screenshot()
        h, w = image.shape[:2]
        labels = self.ocr(image[int(h * .95):, int(w * .18):])
        return sorted((label.text.strip(), label.box.x) for label in labels
                      if re.fullmatch(r"[\u4e00-\u9fff]{3,8}", label.text.strip()))

    def find_activity_tab(self, name, *, toward_start, click=False):
        previous = None
        unchanged = 0
        for attempt in range(25):
            if not self.activity_visible():
                raise RuntimeError("活动界面已离开，停止查找页签")
            if self.region_text(f"^{name}$", (.15, .88, 1, 1), click=click):
                return
            current = self.tab_signature()
            same = (bool(current) and previous is not None and len(current) == len(previous)
                    and all(a[0] == b[0] and abs(a[1] - b[1]) <= 8
                            for a, b in zip(current, previous)))
            unchanged = unchanged + 1 if same else 0
            if unchanged >= 2:
                raise RuntimeError(f"活动页签已到边界或滑动未生效，未找到{name}，已停止滑动")
            previous = current
            if attempt == 24:
                break
            # Earlier tabs are on the left: drag right to reveal them.
            # After finding the calendar, drag left to search later tabs.
            self.swipe_tabs(left=not toward_start)
        raise RuntimeError(f"活动页签查找超过滑动上限，未找到{name}")

    def locate(self, _engine):
        self.open_activity()
        self.engine.log("向页签左端查找活动日历（向右拖动页签栏）")
        self.find_activity_tab("活动日历", toward_start=True)
        self.engine.log("已找到活动日历，向页签右侧查找祥瑞聚宝（向左拖动页签栏）")
        self.find_activity_tab("祥瑞聚宝", toward_start=False, click=True)
        if not self.region_text("^祥瑞聚宝$", (0, .03, .48, .18)):
            raise RuntimeError("点击页签后未确认祥瑞聚宝活动界面")
        if not self.region_text("^搜索灵[貅貔]$", (0, .78, .52, .91), click=True):
            raise RuntimeError("未找到搜索灵貅按钮")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.region_text("藏宝灵[貅貔]", (.1, .25, .9, .65)):
                return
            self.pause(.3)
        raise RuntimeError("搜索后未确认藏宝灵貅目标，可能本波已被打完")

    def free_queue(self):
        # Queue capacity comes from the dispatch panel, not from row recognition.
        image = self.screenshot()
        h, w = image.shape[:2]
        hits = self.ocr(image[int(h * .18):int(h * .38), :int(w * .45)],
                        [r"[0-4][/／][1-4]"])
        if len(hits) != 1:
            # The anchored snapshot has an only-rec OCR fallback for the header.
            # All reliable counts matter, not just the disappearing/empty HUD.
            valid, _, occupied = self.snapshot()
            capacity = getattr(self, 'queue_capacity', None)
            if valid:
                if occupied == 0:
                    return True
                if capacity is not None and 0 <= occupied <= capacity:
                    return occupied < capacity
            return None
        match = re.search(r"([0-4])[/／]([1-4])", hits[0].text)
        if not match:
            return None
        used, total = map(int, match.groups())
        capacity = getattr(self, 'queue_capacity', None)
        if capacity is None or used > total or used > capacity:
            return None
        return used < capacity

    def dispatch_from_panel(self, queue=None, *, existing=None, timeout=15):
        existing = existing or []
        self.occupied_before_dispatch = len(existing)
        selected, slots = self.panel(self.screenshot())
        # Allow a short settling period for weak early-slot recognition before
        # selecting a later squad. Always use the latest panel, not stale slots.
        for _ in range(2):
            first_confirmed = next((i for i, slot in enumerate(slots) if slot[0]), len(slots))
            if first_confirmed == 0:
                break
            self.pause(.35)
            selected, slots = self.panel(self.screenshot())
        self.queue_capacity = sum(bool(slot[0]) for slot in slots)
        busy = getattr(self, 'panel_busy', [False] * len(slots))
        # HUD rows were captured before browsing activities. A squad can return
        # during that interval. Confirm its free panel state twice before dropping
        # the stale row, including the guard in the common dispatch flow.
        def returned_rows(current_slots, current_busy):
            return [row for row in existing
                    if any(unlocked and not current_busy[i] and similarity(row.avatar, avatar) >= .65
                           for i, (unlocked, _, avatar) in enumerate(current_slots))
                    and not any(current_busy[i] and similarity(row.avatar, avatar) >= .65
                                for i, (_, _, avatar) in enumerate(current_slots))]

        returned = returned_rows(slots, busy) if hasattr(self, 'panel_busy') else []
        if returned:
            self.pause(.35)
            selected, slots = self.panel(self.screenshot())
            busy = self.panel_busy
            confirmed = returned_rows(slots, busy)
            removed = {id(row) for row in confirmed if any(row is old for old in returned)}
            if removed:
                existing = [row for row in existing if id(row) not in removed]
                self.engine.log(f"面板连续两次确认队伍已空闲，移除 {len(removed)} 条活动打开前的占用记录")
        self.queue_capacity = sum(bool(slot[0]) for slot in slots)
        # Also retain a baseline when pre-dispatch HUD recognition was missing,
        # so the zero-disciples path can still wait for a real return.
        self.occupied_before_dispatch = max(len(existing), sum(busy))
        candidates = [i + 1 for i, (unlocked, _, avatar) in enumerate(slots)
                      if unlocked and not busy[i]
                      and not any(similarity(row.avatar, avatar) >= .65 for row in existing)]
        for i, (unlocked, _, avatar) in enumerate(slots):
            reason = ('行军/返回图标或状态竖条显示占用' if busy[i] else
                      '锁定或队号识别未通过' if not unlocked else
                      '与外出队伍头像匹配' if i + 1 not in candidates else '空闲候选')
            self.engine.log(f"第 {i + 1} 队：{reason}")
        if not candidates:
            raise NoFreeQueue("出征面板没有可确认的空闲队伍")
        queue = candidates[0]
        self.engine.log(f"出征面板：原选中第 {selected} 队，空闲候选 {candidates}，按队号优先选择第 {queue} 队")
        try:
            return super().dispatch_from_panel(queue, existing=existing, timeout=timeout)
        except ZeroDisciples:
            raise
        except (RuntimeError, TimeoutError):
            # Replay only when a positive stamina prompt proves dispatch was blocked.
            if not self.pipeline("通用识别补充体力按钮"):
                raise
            if not self.engine.auto_stamina:
                raise RuntimeError("体力不足，未勾选自动补体")
            if not self.engine._try_auto_stamina(self.tasker):
                raise RuntimeError("自动补体未成功或没有可用体力来源")
            return super().dispatch_from_panel(queue, existing=existing, timeout=timeout)


def run(engine, case):
    count = attack_count((case.parameters or {}).get("attack_count", 1))
    flow = Pixiu(engine)
    for completed in range(count):
        if not flow.pipeline("通用行军进入大地图"):
            raise RuntimeError("无法通过通用方法进入大地图")
        deadline = time.monotonic() + 900
        waiting_logged = False
        while True:
            # First run discovers actual capacity from the panel. Thereafter,
            # stay in the world until the HUD positively confirms a free slot;
            # an unreadable frame must not reopen the activity while all are busy.
            if (not waiting_logged and completed == 0) or flow.free_queue() is True:
                try:
                    flow.dispatch(None, select_target=flow.locate)
                    break
                except ZeroDisciples:
                    flow.close_and_wait_for_return(flow.occupied_before_dispatch, deadline)
                    continue
                except NoFreeQueue:
                    flow.close_dispatch_panel()
            if not waiting_logged:
                engine.log("尚未确认空闲队列，留在大世界检测左上角小队状态……")
                waiting_logged = True
            if time.monotonic() >= deadline:
                raise TimeoutError(f"等待空闲队列超时；已成功出征 {completed}/{count} 次")
            flow.pause(1)
        engine.log(f"貔貅成功出征 {completed + 1}/{count} 次")
    return f"已完成 {count} 次貔貅出征（以确认小队出发计数）"
