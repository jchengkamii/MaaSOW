"""Shared dispatch-panel recovery and queue policy for all march tasks."""
from __future__ import annotations
import math
import re
import time
from maa.pipeline import JAnd, JRecognitionType
from .state import MarchState

class NoFreeQueue(RuntimeError):
    """No selected squad is confirmed idle."""

class ZeroDisciples(RuntimeError):
    """No dispatch was issued because the squad has no disciples."""

class RelocateAfterStamina(RuntimeError):
    """Stamina was replenished before dispatch but the panel closed."""

class DispatchPanel:
    dispatch_caption = '出征'
    dispatch_states = (MarchState.OUTBOUND, MarchState.FIGHTING)
    target_tooltip_pattern = r'(?!)'
    diagnostic_name = 'march'

    def activity_visible(self):
        return False

    def target_dispatch_point(self, image):
        # A generic coordinate target has no identity proof for a second click.
        return None

    def open_target_panel(self, timeout=8):
        deadline = time.monotonic() + timeout
        previous, stable = None, 0
        while time.monotonic() < deadline:
            image = self.screenshot()
            point = self.target_dispatch_point(image)
            if point is not None:
                tolerance = 6 * image.shape[1] / 720
                stable = (stable + 1 if previous is not None
                          and max(abs(a-b) for a,b in zip(point, previous)) <= tolerance else 1)
                previous = point
                if stable >= 3:
                    self.click(*point)
                    self.pause(.4)
                    return True
            else:
                previous, stable = None, 0
            self.pause(.2)
        return False

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

    def dispatch_panel_visible(self, image):
        # Recovery-only evidence: never infer the selected squad or dispatch
        # from these anchors. The actual dispatch still uses panel().
        h, w = image.shape[:2]
        buttons = self.ocr(image[int(h * .5):int(h * .86)], [f"^{self.dispatch_caption}$"])
        if len(buttons) != 1:
            return False
        for q, center in enumerate((.19, .396, .605, .816), 1):
            crop = image[int(h * .875):int(h * .925),
                         int(w * (center - .09)):int(w * (center - .025))]
            if self.slot_number(crop, q):
                return True
        return False

    def recovery_state(self):
        image = self.screenshot()
        h, w = image.shape[:2]
        labels = self.ocr(image[int(h * .25):int(h * .85)], [f"弟子数量|{self.target_tooltip_pattern}"])
        if any('弟子数量' in label.text for label in labels):
            return '出征弹窗'
        if self.templates(image[int(h * .65):], 'bubble', .65):
            return '出征弹窗'
        if self.dispatch_panel_visible(image):
            return '出征弹窗'
        if self.activity_visible():
            return '活动界面'
        if any(re.search(self.target_tooltip_pattern, label.text) for label in labels):
            return '目标弹窗'
        world = self.recognize(image, JRecognitionType.And, JAnd(all_of=['通用行军确认大地图']))
        return '大世界默认态' if world.hit else '其他界面'

    def recover_world(self):
        confirmations = 0
        popup_attempts = 0
        for attempt in range(10):
            state = self.recovery_state()
            self.engine.log(f"恢复界面 {attempt + 1}/10：{state}")
            if state == '大世界默认态':
                confirmations += 1
                if confirmations == 2:
                    return
            else:
                confirmations = 0
                if state in ('出征弹窗', '目标弹窗'):
                    image = self.screenshot()
                    points = ((.12, .20), (.5, .16), (.85, .20))
                    if popup_attempts < len(points):
                        x, y = points[popup_attempts]
                        self.click(image.shape[1] * x, image.shape[0] * y)
                    else:
                        self.engine.log('弹窗关闭未生效，改用通用返回流程')
                        self.pipeline('通用行军进入大地图')
                        popup_attempts = -1
                    popup_attempts += 1
                else:
                    popup_attempts = 0
                    self.pipeline('通用行军进入大地图')
            self.pause(.5)
        self.record_panel_failure(self.screenshot())
        raise RuntimeError('恢复失败：未能连续确认无出征弹窗的大世界默认态')

    def reconcile_pending_dispatch(self):
        from .march import similarity, new_dispatched_row
        if getattr(self, 'pending_dispatch', False) is not True:
            return False
        self.engine.log('已尝试点击出征，先核实队伍，不重复派遣')
        previous, confirmations = None, 0
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            valid, rows, count = self.snapshot()
            candidate = None
            if valid:
                matches = [row for row in rows if similarity(row.avatar, self.pending_avatar) >= .65]
                if len(matches) == 1 and matches[0].status in self.dispatch_states:
                    candidate = matches[0]
                elif self.pending_baseline_reliable:
                    candidate = new_dispatched_row(self.pending_rows, rows, count)
                    if candidate is not None and candidate.status not in self.dispatch_states:
                        candidate = None
            if candidate is None:
                confirmations, previous = 0, None
            else:
                confirmations = confirmations + 1 if previous is not None and similarity(previous.avatar, candidate.avatar) >= .85 else 1
                previous = candidate
                if confirmations >= 3:
                    self.pending_dispatch = False
                    handle = getattr(self, 'pending_handle', None)
                    if handle is not None:
                        handle.avatar = candidate.avatar
                        handle.last_count = count
                        handle.tracker.observe(visible=True, status=candidate.status, reliable=True)
                    self.engine.log('恢复后连续三帧确认已出征，继续跟踪对应队伍')
                    return True
            self.pause(.5)
        raise RuntimeError('已回到大世界，但之前出征结果仍不明确；停止以免重复派遣或错误计数')

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
                self.engine.log("已确认队列占用减少，继续定位目标")
                return
            self.pause(1)
        raise TimeoutError("弟子数量为 0，等待队伍返回超时；本次未出征、未计数")

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

    def free_queue(self):
        from .march import similarity
        allowed = getattr(self, 'allowed_queues', [1, 2, 3, 4])
        if allowed != [1, 2, 3, 4]:
            # HUD count alone cannot tell whether a selected squad is free.
            valid, rows, occupied = self.snapshot()
            avatars = getattr(self, 'allowed_avatars', {})
            if not valid or occupied != len(rows) or not avatars:
                self.selected_free_candidates = set()
                return None
            free = {q for q, avatar in avatars.items() if q in allowed
                    and not any(similarity(row.avatar, avatar) >= .65 for row in rows)}
            previous = getattr(self, 'selected_free_candidates', set())
            self.selected_free_candidates = free
            return bool(free & previous)
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

    def ready_dispatch_panel(self):
        # This runs before selecting or dispatching a squad. Only recapture on
        # transition failures: never re-click attack or dispatch speculatively.
        def wait_panel():
            for attempt in range(4):
                image = self.screenshot()
                try:
                    return self.panel(image)
                except InterruptedError:
                    raise
                except RuntimeError:
                    if attempt == 3:
                        self.record_panel_failure(image)
                        raise
                    self.pause(.4)

        try:
            return wait_panel()
        except InterruptedError:
            raise
        except RuntimeError as exc:
            # Attack can miss while the map camera settles. Retry at most once,
            # only when the same target tooltip and radial attack icon remain.
            # This is before squad dispatch, never a retry of the dispatch click.
            if self.target_dispatch_point(self.screenshot()) is not None:
                self.engine.log("尚停留在目标界面，等待图标稳定后补点一次面板入口")
                if self.open_target_panel(3):
                    try:
                        return wait_panel()
                    except InterruptedError:
                        raise
                    except RuntimeError as retry_error:
                        exc = retry_error
            self.engine.log(f"进攻后出征面板尚未确认：{exc}；检查体力不足提示")
            if not self.pipeline("通用识别补充体力按钮"):
                raise RuntimeError(f"进攻后连续四次未确认出征面板，且未发现体力不足提示：{exc}") from exc
            if not self.engine.auto_stamina:
                raise RuntimeError("体力不足，未勾选自动补体") from exc
            if not self.engine._try_auto_stamina(self.tasker):
                raise RuntimeError("自动补体未成功或没有可用体力来源") from exc
        try:
            return wait_panel()
        except InterruptedError:
            raise
        except RuntimeError as exc:
            if not self.pipeline("通用行军进入大地图"):
                raise RuntimeError("补体后未确认出征面板，且无法返回大世界") from exc
            raise RelocateAfterStamina("进攻阶段已补体，面板已关闭，重新定位目标") from exc

    def record_panel_failure(self, image):
        # Preserve the exact failed frame, not a later screenshot after recovery.
        from pathlib import Path
        from PIL import Image
        try:
            folder = Path(__file__).resolve().parents[4] / 'debug'
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f'{getattr(self, 'diagnostic_name', 'march')}_panel_failure.png'
            Image.fromarray(image[:, :, ::-1]).save(path)
            self.engine.log(f"出征面板识别失败原图已保存：{path}，尺寸 {image.shape[1]}x{image.shape[0]}")
        except Exception as exc:
            self.engine.log(f"保存面板诊断截图失败：{exc}")

    def dispatch_from_panel(self, queue=None, *, existing=None, timeout=15):
        from .march import similarity
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("出征确认超时必须为有限正数")
        if queue is not None and (type(queue) is not int or not 1 <= queue <= 4):
            raise ValueError("queue 必须是 1–4 或 None")
        allowed = getattr(self, 'allowed_queues', [1, 2, 3, 4])
        if queue is not None and queue not in allowed:
            raise ValueError(f"第 {queue} 队未勾选，不参与出征")
        existing = existing or []
        self.occupied_before_dispatch = len(existing)
        selected, slots = self.ready_dispatch_panel()
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
        self.allowed_avatars = {i + 1: avatar for i, (unlocked, _, avatar) in enumerate(slots)
                                if unlocked and i + 1 in allowed}
        self.selected_free_candidates = set()
        candidates = [i + 1 for i, (unlocked, _, avatar) in enumerate(slots)
                      if i + 1 in allowed and (queue is None or i + 1 == queue)
                      and unlocked and not busy[i]
                      and not any(similarity(row.avatar, avatar) >= .65 for row in existing)]
        for i, (unlocked, _, avatar) in enumerate(slots):
            reason = ('未勾选，不参与出征' if i + 1 not in allowed else
                      '行军/返回图标或状态竖条显示占用' if busy[i] else
                      '锁定或队号识别未通过' if not unlocked else
                      '与外出队伍头像匹配' if i + 1 not in candidates else '空闲候选')
            self.engine.log(f"第 {i + 1} 队：{reason}")
        if not candidates:
            if queue is not None and hasattr(self, "blocked"):
                self.blocked[queue] = (slots[queue - 1][2], 0)
            raise NoFreeQueue("所选出征队列中没有可确认的空闲队伍")
        queue = candidates[0]
        self.engine.log(f"出征面板：原选中第 {selected} 队，空闲候选 {candidates}，按队号优先选择第 {queue} 队")
        self.pending_avatar = slots[queue - 1][2]
        self.pending_rows = existing
        self.pending_baseline_reliable = getattr(self, 'pre_snapshot_reliable', False)
        self.pending_dispatch = False
        try:
            handle = self._submit_from_panel(queue, existing=existing, timeout=timeout)
            self.pending_dispatch = False
            return handle
        except ZeroDisciples:
            raise
        except InterruptedError:
            raise
        except (RuntimeError, TimeoutError):
            # Replay only when a positive stamina prompt proves dispatch was blocked.
            if not self.pipeline("通用识别补充体力按钮"):
                if getattr(self, 'pending_dispatch', False) is True:
                    self.recover_world()
                    if self.reconcile_pending_dispatch():
                        return self.pending_handle
                raise
            if not self.engine.auto_stamina:
                raise RuntimeError("体力不足，未勾选自动补体")
            if not self.engine._try_auto_stamina(self.tasker):
                raise RuntimeError("自动补体未成功或没有可用体力来源")
            self.pending_dispatch = False  # Positive stamina prompt proves rejection.
            handle = self._submit_from_panel(queue, existing=existing, timeout=timeout)
            self.pending_dispatch = False
            return handle
