"""Locate treasure pixiu through activity tabs and reuse the common march flow."""
from __future__ import annotations

import re
import time

from maa.pipeline import JRecognitionType, JTemplateMatch

from agent.custom.action.march.march import March
from agent.custom.action.march.dispatch_panel import NoFreeQueue, ZeroDisciples, RelocateAfterStamina


def attack_count(value):
    if isinstance(value, bool) or not re.fullmatch(r"[1-9]\d{0,3}|10000", str(value)):
        raise ValueError("进攻次数必须为 1–10000 的整数")
    return int(value)


def attack_queues(value):
    if isinstance(value, str):
        if not re.fullmatch(r"[1-4](?:,[1-4])*", value):
            raise ValueError("请至少勾选一个出征队列（1、2、3、4）")
        value = [int(item) for item in value.split(',')]
    if (not isinstance(value, (list, tuple)) or not value
            or any(type(item) is not int or item not in range(1, 5) for item in value)
            or len(set(value)) != len(value)):
        raise ValueError("出征队列必须为 1、2、3、4 中至少一个不重复的队号")
    return sorted(value)


class Pixiu(March):
    target_tooltip_pattern = r'藏宝灵[貅貔]'
    diagnostic_name = 'pixiu'

    def target_dispatch_point(self, image):
        return self.pixiu_attack_point(image)

    def open_target_panel(self, timeout=8):
        return self.attack_pixiu(timeout)


    def text_button(self, text, timeout=8):
        if text == "进攻":
            return self.attack_pixiu(timeout)
        return super().text_button(text, timeout=timeout)


    def pixiu_attack_point(self, image):
        h, w = image.shape[:2]
        left, top = int(w * .1), int(h * .25)
        titles = self.ocr(image[top:int(h * .65), left:int(w * .9)], ["藏宝灵[貅貔]"])
        if len(titles) != 1:
            return None
        title = titles[0].box
        # Search below the selected target tooltip, not other monsters' names.
        # The radial attack icon is centered underneath the tooltip and can be
        # recognized even when nearby labels merge with the caption "进攻".
        x0 = max(0, int(left + title.x - 80 * w / 720))
        x1 = min(w, int(left + title.x + title.w + 160 * w / 720))
        y0 = top + title.y + title.h
        y1 = min(int(h * .90), int(y0 + 620 * w / 720))
        icons = self.templates(image[y0:y1, x0:x1], "attack", .7)
        if len(icons) != 1:
            return None
        icon = icons[0].box
        return x0 + icon.x + icon.w / 2, y0 + icon.y + icon.h / 2

    def attack_pixiu(self, timeout):
        return super().open_target_panel(timeout)


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
        # Floating map text can join the caption in a single OCR box (for
        # example "[逍玩法活动]"). The actual click still requires the icon.
        labels = [result for result in self.ocr(roi, ["玩法活动"])
                  if "玩法活动" in result.text]
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
        for attempt in range(6):
            if self.region_text("^祥瑞聚宝$", (0, .03, .48, .18)):
                break
            if attempt == 5:
                self.record_panel_failure(self.screenshot())
                raise RuntimeError("点击页签后未确认祥瑞聚宝活动界面")
            self.pause(.3)
        if not self.region_text("^搜索灵[貅貔]$", (0, .78, .52, .91), click=True):
            raise RuntimeError("未找到搜索灵貅按钮")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.region_text("藏宝灵[貅貔]", (.1, .25, .9, .65)):
                return
            self.pause(.3)
        raise RuntimeError("搜索后未确认藏宝灵貅目标，可能本波已被打完")


def run(engine, case):
    count = attack_count((case.parameters or {}).get("attack_count", 1))
    queues = attack_queues((case.parameters or {}).get("attack_queues", [1, 2, 3, 4]))
    flow = Pixiu(engine)
    flow.allowed_queues = queues
    engine.log(f"貔貅参与出征队列：{','.join(map(str, queues))}")
    for completed in range(count):
        if not flow.pipeline("通用行军进入大地图"):
            flow.recover_world()
        deadline = time.monotonic() + 900
        waiting_logged = False
        stamina_relocations = 0
        recoveries = 0
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
                except RelocateAfterStamina as exc:
                    stamina_relocations += 1
                    if stamina_relocations > 2 or time.monotonic() >= deadline:
                        raise RuntimeError("补体后反复无法进入出征面板，已停止；本次未计数") from exc
                    engine.log(str(exc))
                    continue
                except NoFreeQueue:
                    flow.close_dispatch_panel()
                except InterruptedError:
                    raise
                except (RuntimeError, TimeoutError) as exc:
                    recoveries += 1
                    engine.log(f"检测失败，尝试恢复 {recoveries}/3：{exc}")
                    if recoveries > 3 or time.monotonic() >= deadline:
                        raise RuntimeError(f"连续恢复仍失败；已成功出征 {completed}/{count} 次：{exc}") from exc
                    flow.recover_world()
                    if flow.reconcile_pending_dispatch() is True:
                        break
                    continue
            if not waiting_logged:
                engine.log("尚未确认空闲队列，留在大世界检测左上角小队状态……")
                waiting_logged = True
            if time.monotonic() >= deadline:
                raise TimeoutError(f"等待空闲队列超时；已成功出征 {completed}/{count} 次")
            flow.pause(1)
        engine.log(f"貔貅成功出征 {completed + 1}/{count} 次")
    return f"已完成 {count} 次貔貅出征（以确认小队出发计数）"
