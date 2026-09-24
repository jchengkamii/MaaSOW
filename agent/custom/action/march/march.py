"""Single dispatch with a reusable handle for concurrent marches.

Coordinates supplied by callers are Maa screenshot coordinates (short side 720).
This module does not choose enemies, adjust disciples, or purchase stamina.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time

import numpy as np
from maa.pipeline import JAnd, JOCR, JRecognitionType, JTemplateMatch
from maa.tasker import Tasker
from maa.define import Rect

from .state import MarchState, MarchTracker, parse_status


def portrait(image):
    h, w = image.shape[:2]
    image = image[int(h * .08):int(h * .72), int(w * .12):int(w * .85)]
    if image.size == 0:
        raise RuntimeError("无法截取队伍头像")
    ys = np.linspace(0, image.shape[0] - 1, 24).astype(int)
    xs = np.linspace(0, image.shape[1] - 1, 24).astype(int)
    return image[ys[:, None], xs].astype(float)


def similarity(a, b):
    # Queue cards and compact list portraits have slightly different padding.
    best = 0.0
    for dy in range(-4, 5):
        for dx in range(-4, 5):
            aa = a[max(0, dy):min(24, 24 + dy), max(0, dx):min(24, 24 + dx)].ravel()
            bb = b[max(0, -dy):min(24, 24 - dy), max(0, -dx):min(24, 24 - dx)].ravel()
            aa, bb = aa - aa.mean(), bb - bb.mean()
            denominator = np.linalg.norm(aa) * np.linalg.norm(bb)
            if denominator:
                best = max(best, float(aa @ bb / denominator))
    return best


@dataclass
class SquadRow:
    avatar: np.ndarray
    status: MarchState | None


def new_dispatched_row(existing, rows, count):
    """Identify one added active row using same-sized HUD portraits only."""
    if count != len(existing) + 1 or len(rows) != count:
        return None
    assigned = set()
    for old in existing:
        matches = [i for i, row in enumerate(rows) if similarity(old.avatar, row.avatar) >= .80]
        if len(matches) != 1 or matches[0] in assigned:
            return None
        assigned.add(matches[0])
    added = [row for i, row in enumerate(rows) if i not in assigned]
    if len(added) != 1 or added[0].status not in (MarchState.OUTBOUND, MarchState.FIGHTING):
        return None
    return added[0]


@dataclass
class MarchHandle:
    queue: int
    avatar: np.ndarray
    tracker: MarchTracker
    last_count: int = 0


class March:
    def __init__(self, engine):
        self.engine = engine
        if engine._resource is None:
            engine.reload_resources()
        self.controller = engine._controller_for("game")
        self.tasker = Tasker()
        self.tasker.bind(engine._resource, self.controller)
        if not self.tasker.inited:
            raise RuntimeError("通用行军 Tasker 初始化失败")

    def check_stop(self):
        if self.engine.stop_event.is_set():
            raise InterruptedError("用户停止执行")

    def pause(self, seconds):
        self.check_stop()
        if self.engine.stop_event.wait(seconds):
            raise InterruptedError("用户停止执行")

    def screenshot(self):
        self.check_stop()
        image = self.controller.post_screencap().wait().get()
        if image is None or not image.size:
            raise RuntimeError("通用行军截图失败")
        return image

    def job(self, submit):
        self.check_stop()
        with self.engine._state_lock:
            previous = self.engine._current_tasker
            self.engine._current_tasker = self.tasker
        try:
            result = submit().wait()
            self.check_stop()
            return result
        finally:
            with self.engine._state_lock:
                self.engine._current_tasker = previous

    def pipeline(self, entry):
        # Do not use engine's automatic replay: a dispatch is not idempotent.
        return self.job(lambda: self.tasker.post_task(entry)).succeeded

    def recognize(self, image, kind, params):
        result = self.job(lambda: self.tasker.post_recognition(kind, params, image))
        detail = result.get()
        if detail is None or not detail.nodes:
            raise RuntimeError("行军识别未返回结果")
        recognition = detail.nodes[0].recognition
        for result in recognition.filtered_results:
            if isinstance(getattr(result, "box", None), (list, tuple)):
                result.box = Rect(*result.box)
        return recognition

    def ocr(self, image, expected=None, only_rec=False):
        # Physical crop: the project's full-screen fallback cannot see timers.
        detail = self.recognize(image.copy(), JRecognitionType.OCR,
                                JOCR(expected=expected or [], threshold=.6, only_rec=only_rec, model="march_zh"))
        return detail.filtered_results if detail.hit else []

    def templates(self, image, name, threshold=.72):
        detail = self.recognize(image.copy(), JRecognitionType.TemplateMatch,
                               JTemplateMatch(template=[f"Common/March/{name}.png"],
                                              threshold=[threshold], order_by="Vertical"))
        return detail.filtered_results if detail.hit else []

    def click(self, x, y):
        self.check_stop()
        if not self.controller.post_click(int(x), int(y)).wait().succeeded:
            raise RuntimeError("通用行军点击失败")

    def text_button(self, text, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            image = self.screenshot()
            # Exclude top HUD and bottom chat; search variable radial/panel positions.
            y0, y1 = int(image.shape[0] * .25), int(image.shape[0] * .86)
            hits = self.ocr(image[y0:y1], [f"^{text}$"])
            if len(hits) == 1:
                box = hits[0].box
                if text == "进攻":
                    # The caption is outside the radial button's hit area.
                    cx, cy = box.x + box.w / 2, y0 + box.y
                    scale = image.shape[1] / 720
                    left, top = max(0, int(cx - 75 * scale)), max(0, int(cy - 115 * scale))
                    icons = self.templates(image[top:int(cy), left:int(cx + 75 * scale)], "attack", .7)
                    if len(icons) != 1:
                        self.pause(.2)
                        continue
                    icon = icons[0].box
                    self.click(left + icon.x + icon.w / 2, top + icon.y + icon.h / 2)
                else:
                    self.click(box.x + box.w / 2, y0 + box.y + box.h / 2)
                self.pause(.4)
                return True
            self.pause(.2)
        return False

    def slot_number(self, crop, number):
        expected = [f"^{number}$"]
        if self.ocr(crop, expected, only_rec=True):
            return True
        # Isolate the white digit from the coloured portrait behind it, then
        # pad/upscale for single-character OCR. Keep the confidence threshold.
        white = (crop.min(axis=2) >= 200) & (crop.max(axis=2).astype(int) - crop.min(axis=2) < 40)
        clean = np.repeat((white.astype(np.uint8) * 255)[:, :, None], 3, axis=2)
        clean = np.pad(clean, ((4, 4), (4, 4), (0, 0)))
        clean = np.repeat(np.repeat(clean, 3, axis=0), 3, axis=1)
        return bool(self.ocr(clean, expected, only_rec=True))

    def slot_busy(self, image, left, top, size):
        h, w = image.shape[:2]
        # Status badge protrudes above/left of the portrait; the bar sits on
        # its right edge. Neither is part of the portrait identity comparison.
        badge = image[max(0, top - int(size * .18)):top + int(size * .36),
                      max(0, left - int(size * .18)):left + int(size * .38)]
        for name in ("occupied_outbound", "occupied_returning"):
            if self.templates(badge, name, .78):
                return True
        bar = image[max(0, top):min(h, top + size),
                    max(0, left + int(size * .90)):min(w, left + int(size * 1.12))]
        if bar.size == 0:
            return False
        b, g, r = (bar[:, :, i].astype(int) for i in range(3))
        green = (g > 170) & (g > r * 1.3) & (g > b * 1.3)
        yellow = (r > 190) & (g > 160) & (b < 100)
        red = (r > 190) & (g < 110) & (b < 110)
        # Require a thick, long bar; thin portrait/selection borders do not count.
        columns = (green | yellow | red).sum(axis=0) >= size * .65
        run = 0
        for coloured in columns:
            run = run + 1 if coloured else 0
            if run >= max(4, round(size * .035)):
                return True
        return False

    def panel(self, image):
        h, w = image.shape[:2]
        origin = int(h * .65)
        hits = self.templates(image[origin:], "bubble", .65)
        if len(hits) != 1:
            raise RuntimeError("无法唯一识别出征面板气泡指向")
        box = hits[0].box
        center = box.x + box.w / 2
        centers = [w * value for value in (.19, .396, .605, .816)]
        selected = min(range(4), key=lambda i: abs(centers[i] - center))
        if abs(centers[selected] - center) > w * .075:
            raise RuntimeError("出征面板气泡未指向有效队列")
        scale = w / 690
        top = round(origin + box.y + box.h + 21 * scale)
        size = round(110 * scale)
        slots = []
        busy = []
        for i, x in enumerate(centers):
            left = round(x - size / 2)
            crop = image[top:top + size, left:left + size]
            if crop.shape[:2] != (size, size):
                raise RuntimeError("队列区域超出截图")
            blocked = self.templates(crop, "locked", .65) or self.templates(crop, "monthly", .65)
            # Positive number recognition is required; unknown slots are never clicked.
            numbered = False if blocked else self.slot_number(crop[int(size * .72):, :int(size * .25)], i + 1)
            slots.append((numbered, (x, top + size / 2), portrait(crop)))
            busy.append(self.slot_busy(image, left, top, size))
        self.panel_busy = busy
        return selected + 1, slots

    def row_anchors(self, image):
        # Gathering squads show recall, while marching squads show speed-up.
        anchors = list(self.templates(image, "speed", .75))
        for candidate in self.templates(image, "recall", .75):
            if not any(abs(candidate.box.y - anchor.box.y) < 15 and
                       abs(candidate.box.x - anchor.box.x) < 15 for anchor in anchors):
                anchors.append(candidate)
        return sorted(anchors, key=lambda anchor: anchor.box.y)

    def snapshot(self):
        image = self.screenshot()
        h, w = image.shape[:2]
        # Find the header in the left upper half, then inspect row text separately.
        xend, ystart, yend = int(w * .37), int(h * .18), int(h * .62)
        titles = self.templates(image[ystart:yend, :xend], "header", .75)
        if not titles:
            # With no deployed squads the entire list may disappear.
            world = self.recognize(image, JRecognitionType.And,
                                   JAnd(all_of=["通用行军确认大地图"]))
            anchors = self.row_anchors(image[ystart:yend, :xend])
            return bool(world.hit and not anchors), [], 0
        if len(titles) != 1:
            return False, [], 0
        title = titles[0].box
        top = ystart + title.y
        counts = self.ocr(image[top:top + title.h, int(w * .27):xend],
                          [r"[0-4][/／][1-4]"])
        if len(counts) != 1:
            counts = self.ocr(image[top:top + title.h, int(w * .27):xend],
                              [r"[0-4][/／][1-4]"], only_rec=True)
        if len(counts) != 1:
            return False, [], 0
        match = re.search(r"([0-4])[/／]([1-4])", counts[0].text)
        count, maximum = map(int, match.groups())
        if count > maximum:
            return False, [], count
        start = top + title.h
        anchors = self.row_anchors(image[start:yend, :xend])
        if len(anchors) != count:
            return False, [], count
        rows = []
        scale = w / 690
        for anchor in anchors:
            x, y = anchor.box.x, start + anchor.box.y
            left, top, size = round(x - 197 * scale), round(y - 7 * scale), round(42 * scale)
            if min(left, top) < 0:
                return False, [], count
            avatar = portrait(image[top:top + size, left:left + size])
            # Top 25 px contain status; the timer below is never OCR input.
            text = self.ocr(image[top - round(6 * scale):top + round(20 * scale),
                                  left + round(43 * scale):x - round(5 * scale)], only_rec=True)
            statuses = [parse_status(r.text) for r in text]
            status = next((s for s in statuses if s is not None), None)
            rows.append(SquadRow(avatar, status))
        # A collapsed list cannot provide the row anchors for a nonzero count.
        return True, rows, count

    def pre_dispatch_rows(self):
        self.pre_snapshot_reliable = False
        for attempt in range(3):
            valid, rows, _ = self.snapshot()
            if valid:
                self.pre_snapshot_reliable = True
                return rows
            if attempt < 2:
                self.pause(.3)
        raise RuntimeError("无法读取出征前小队列表，请展开列表并关闭遮挡界面")

    def dispatch(self, target, queue=None, select_target=None, timeout=15):
        """Enter world, call target selector (or click point), dispatch exactly once."""
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("出征确认超时必须为有限正数")
        if queue is not None and (type(queue) is not int or not 1 <= queue <= 4):
            raise ValueError("queue 必须是 1–4 或 None")
        if select_target is None and (not isinstance(target, (tuple, list)) or
                                      len(target) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in target)):
            raise ValueError("调用方必须提供目标坐标或 select_target 回调")
        if not self.pipeline("通用行军进入大地图"):
            raise RuntimeError("无法进入大地图")
        existing = self.pre_dispatch_rows()
        if select_target is not None:
            select_target(self.engine)
        else:
            image = self.screenshot()
            if not (0 <= target[0] < image.shape[1] and 0 <= target[1] < image.shape[0]):
                raise ValueError("目标坐标超出 Maa 截图")
            self.click(*target)
        if not self.text_button("进攻"):
            raise RuntimeError("未找到目标的进攻按钮")
        self.pause(.6)
        return self.dispatch_from_panel(queue=queue, existing=existing, timeout=timeout)

    def dispatch_from_panel(self, queue=None, *, existing=None, timeout=15):
        """Continue an already-open dispatch panel without navigating away."""
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("出征确认超时必须为有限正数")
        if queue is not None and (type(queue) is not int or not 1 <= queue <= 4):
            raise ValueError("queue 必须是 1–4 或 None")
        baseline_known = existing is not None and getattr(self, 'pre_snapshot_reliable', True)
        existing = existing or []
        selected, slots = self.panel(self.screenshot())
        desired = queue or selected
        if getattr(self, 'panel_busy', [False] * 4)[desired - 1]:
            raise RuntimeError(f"第 {desired} 队正在外出，未出征")
        if not slots[desired - 1][0]:
            raise RuntimeError(f"第 {desired} 队未解锁或无法确认，未出征")
        if selected != desired:
            self.click(*slots[desired - 1][1])
            self.pause(.6)
            selected, slots = self.panel(self.screenshot())
            if selected != desired or not slots[desired - 1][0]:
                raise RuntimeError("队列切换未生效")
        # At most one auto-deploy click, followed by a fresh button recognition.
        if self.text_button("一键上阵", timeout=.6):
            self.pause(.6)
        selected, slots = self.panel(self.screenshot())
        if selected != desired or not slots[desired - 1][0]:
            raise RuntimeError("出征前队列确认失败")
        selected_avatar = slots[desired - 1][2]
        if getattr(self, 'panel_busy', [False] * 4)[desired - 1]:
            raise RuntimeError(f"第 {desired} 队出现占用标记，未点击出征")
        if any(similarity(row.avatar, selected_avatar) >= .65 for row in existing):
            raise RuntimeError("所选队伍已在行军或与已有队伍头像相同，无法唯一跟踪")
        if not self.text_button("出征"):
            raise RuntimeError("未找到出征按钮")
        handle = MarchHandle(desired, selected_avatar, MarchTracker())
        deadline = time.monotonic() + timeout
        previous_added = None
        added_confirmations = 0
        next_diagnostic = 0
        while time.monotonic() < deadline:
            valid, rows, count = self.snapshot()
            scores = [similarity(row.avatar, selected_avatar) for row in rows]
            matches = [row for row, score in zip(rows, scores) if score >= .65]
            confirmed = None
            method = "头像唯一匹配"
            if valid and len(matches) == 1 and matches[0].status is not None:
                confirmed = matches[0]
            else:
                added = new_dispatched_row(existing, rows, count) if valid and baseline_known else None
                if added is None:
                    previous_added = None
                    added_confirmations = 0
                else:
                    added_confirmations = (added_confirmations + 1 if previous_added is not None
                                           and similarity(previous_added.avatar, added.avatar) >= .85 else 1)
                    previous_added = added
                    if added_confirmations >= 3:
                        confirmed = added
                        method = "原队伍全部保留且唯一新增行军队伍，连续三帧确认"
            if confirmed is not None:
                handle.avatar = confirmed.avatar
                handle.last_count = count
                handle.tracker.observe(visible=True, status=confirmed.status, reliable=True)
                self.engine.log(f"第 {desired} 队已出征：{handle.tracker.state}；确认方式：{method}")
                return handle
            if time.monotonic() >= next_diagnostic:
                self.engine.log(f"第 {desired} 队出征确认中：列表可靠={valid}，占用={count}，"
                                f"出征前基线可靠={baseline_known}，原队伍数={len(existing)}，"
                                f"头像相似度={[round(score, 3) for score in scores]}，"
                                f"状态={[row.status for row in rows]}，新增确认帧={added_confirmations}")
                next_diagnostic = time.monotonic() + 3
            self.pause(.3)
        raise TimeoutError("已点击出征，但未确认对应小队；不会重复点击出征")

    def poll(self, handle):
        if handle.tracker.state == MarchState.COMPLETED:
            return True
        valid, rows, count = self.snapshot()
        matches = [row for row in rows if similarity(row.avatar, handle.avatar) >= .72]
        previous = handle.tracker.state
        done = handle.tracker.observe(visible=bool(matches),
                    status=matches[0].status if len(matches) == 1 else None,
                    reliable=valid and len(matches) <= 1,
                    count_decreased=count < handle.last_count)
        if valid and len(matches) == 1:
            handle.last_count = count
        if handle.tracker.state != previous:
            self.engine.log(f"第 {handle.queue} 队：{handle.tracker.state}")
        return done

    def wait(self, handle, timeout=900, poll_interval=.5):
        if not math.isfinite(timeout) or timeout <= 0 or not math.isfinite(poll_interval) or poll_interval <= 0:
            raise ValueError("等待超时和轮询间隔必须为有限正数")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.poll(handle):
                return handle
            self.pause(poll_interval)
        raise TimeoutError(f"第 {handle.queue} 队未确认返回后消失，行军等待超时")


def run(engine, case):
    """Case-compatible entry. Caller owns the automation mutex, as for ordinary cases."""
    params = case.parameters or {}
    timeout = float(params.get("timeout", 900))
    interval = float(params.get("poll_interval", .5))
    if not all(math.isfinite(v) and v > 0 for v in (timeout, interval)):
        raise ValueError("timeout 和 poll_interval 必须为有限正数")
    march = March(engine)
    handle = march.dispatch(params.get("target"), params.get("queue"))
    march.wait(handle, timeout=timeout, poll_interval=interval)
    return f"第 {handle.queue} 队行军结束（已确认返回后消失）"
