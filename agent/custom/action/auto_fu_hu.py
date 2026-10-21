"""Rotate selected Fuhu squads as soon as the previous march starts returning."""
from __future__ import annotations

import re
import time

from maa.pipeline import JAnd, JRecognitionType

from agent.custom.action.auto_pixiu import attack_count, attack_queues
from agent.custom.action.march.dispatch_panel import NoFreeQueue, ZeroDisciples
from agent.custom.action.march.march import March, similarity
from agent.custom.action.march.state import MarchState


class FuHuFinished(Exception):
    """The activity icon has disappeared on the unobstructed world map."""


class FuHu(March):
    target_tooltip_pattern = r'等级\s*\d+\s*\S+'
    diagnostic_name = 'fu_hu'

    def check_icon_completion(self):
        for attempt in range(3):
            icon = self.recognize(self.screenshot(), JRecognitionType.And,
                                  JAnd(all_of=['伏虎降妖定位入口']))
            if icon.hit or self.recovery_state() != '大世界默认态':
                return
            if attempt < 2:
                self.pause(.35)
        raise FuHuFinished('已连续三次确认大地图左下角任务图标消失')

    def read_squad_row(self, image, start, box):
        row, texts = super().read_squad_row(image, start, box)
        if row is None or row.status is not None:
            return row, texts
        # The common reader has already physically excluded the timer below
        # this row and retried with the left edge/right map text cropped out.
        # Map labels can remain attached even after cropping, including both
        # power digits and Chinese names (返回01724653 / 返回龙王费日).
        # Read the status only at the start of this verified squad's strip;
        # require agreement from at least two differently cropped reads.
        # Colons/timer text, arbitrary prefixes and conflicting states fail.
        labels = [match[1] for text in texts
                  if (match := re.fullmatch(r'导?(返回|战斗中)[\d\u4e00-\u9fff\[\]【】]{0,12}',
                                           re.sub(r'\s+', '', text)))]
        if len(labels) >= 2 and len(set(labels)) == 1:
            row.status = {'返回': MarchState.RETURNING, '战斗中': MarchState.FIGHTING}[labels[0]]
            self.engine.log(f'伏虎镇伥小队状态裁剪复核：{texts} → {row.status}')
        return row, texts

    def target_dispatch_point(self, image):
        h, w = image.shape[:2]
        left, top = int(w * .1), int(h * .2)
        tooltip = image[top:int(h * .65), left:int(w * .9)]
        titles = self.ocr(tooltip, [self.target_tooltip_pattern])
        # The challenge tooltip distinguishes this personal monster from
        # ordinary map targets; monster names can change between stages.
        if len(titles) != 1 or len(self.ocr(tooltip, ['^挑战者$'])) != 1:
            return None
        box = titles[0].box
        x0 = max(0, int(left + box.x - 80 * w / 720))
        x1 = min(w, int(left + box.x + box.w + 160 * w / 720))
        y0 = top + box.y + box.h
        y1 = min(int(h * .90), int(y0 + 620 * w / 720))
        icons = self.templates(image[y0:y1, x0:x1], 'attack', .7)
        if len(icons) != 1:
            return None
        icon = icons[0].box
        return x0 + icon.x + icon.w / 2, y0 + icon.y + icon.h / 2

    def text_button(self, text, timeout=8):
        if text == '进攻':
            return self.open_target_panel(timeout)
        return super().text_button(text, timeout=timeout)

    def locate(self, _engine):
        for attempt in range(2):
            self.check_icon_completion()
            if not self.pipeline('伏虎降妖定位入口'):
                self.check_icon_completion()
                self.record_panel_failure(self.screenshot())
                raise RuntimeError('未能定位伏虎镇伥入口，且无法确认大地图图标已消失')
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.target_dispatch_point(self.screenshot()) is not None:
                    return
                self.pause(.3)
            # A distant target can require one click to move the camera and a
            # second click to select it. Never retry over an existing popup.
            if attempt or self.recovery_state() != '大世界默认态':
                break
            self.engine.log('首次定位后仍为大地图，可能只移动了镜头；补点一次定位入口')
        self.record_panel_failure(self.screenshot())
        raise RuntimeError('定位后未确认伏虎降妖挑战者弹窗及进攻图标，未派遣队伍')

    def queue_available(self, queue):
        valid, rows, occupied = self.snapshot()
        avatar = getattr(self, 'allowed_avatars', {}).get(queue)
        idle = (valid and occupied == len(rows) and avatar is not None
                and not any(similarity(row.avatar, avatar) >= .65 for row in rows))
        previous = getattr(self, '_idle_queue', None)
        self._idle_queue = queue if idle else None
        return idle and previous == queue

    def close_and_wait_for_return(self, occupied_before, deadline):
        self.close_dispatch_panel()
        self.check_icon_completion()
        if occupied_before <= 0:
            raise RuntimeError('弟子数量为 0，且没有正在外出的队伍可等待返回')
        self.engine.log('弟子数量为 0，等待外出队伍返回或任务图标消失')
        confirmations = 0
        while time.monotonic() < deadline:
            self.check_icon_completion()
            valid, _, occupied = self.snapshot()
            confirmations = confirmations + 1 if valid and occupied < occupied_before else 0
            if confirmations >= 2:
                return
            self.pause(1)
        raise TimeoutError('弟子数量为 0，等待队伍返回超时；本次未出征、未计数')

    def dispatch_next(self, queue):
        deadline = time.monotonic() + 900
        waiting_for_queue = False
        self._idle_queue = None
        while time.monotonic() < deadline:
            if waiting_for_queue:
                self.check_icon_completion()
            if waiting_for_queue and not self.queue_available(queue):
                self.pause(.5)
                continue
            try:
                return self.dispatch(None, queue=queue, select_target=self.locate)
            except NoFreeQueue:
                self.close_dispatch_panel()
                self.engine.log(f'下一勾选队列为第 {queue} 队，尚未确认空闲，等待该队可用后再定位')
                waiting_for_queue = True
            except ZeroDisciples:
                self.close_and_wait_for_return(self.occupied_before_dispatch, deadline)
                waiting_for_queue = False
            except (RuntimeError, TimeoutError):
                # Recover an uncertain submission without ever locating or
                # submitting again until its outcome has been established.
                if getattr(self, 'pending_dispatch', False) is True:
                    self.recover_world()
                    if self.reconcile_pending_dispatch():
                        return self.pending_handle
                raise
        raise TimeoutError('等待伏虎降妖所选队列空闲超时，未再次派遣')

    def confirm_returned_in_panel(self, handle):
        if handle.panel_avatar is None:
            raise RuntimeError(f'第 {handle.queue} 队缺少派遣前头像，不能复核回城状态')
        self.engine.log(f'第 {handle.queue} 队连续消失，打开面板只读复核原队伍是否已回城')
        try:
            self.locate(self.engine)
            if not self.open_target_panel():
                raise RuntimeError('无法打开出征面板复核回城状态')
            for _ in range(2):
                _, slots = self.ready_dispatch_panel()
                unlocked, _, avatar = slots[handle.queue - 1]
                busy = self.panel_busy[handle.queue - 1]
                score = similarity(avatar, handle.panel_avatar)
                self.engine.log(f'第 {handle.queue} 队回城复核：队号可用={unlocked}，'
                                f'占用={busy}，头像相似度={score:.3f}')
                if not unlocked or busy or score < .80:
                    return False
                self.pause(.35)
            return True
        finally:
            self.recover_world()

    def poll_return(self, handle):
        # Keep the common state rules, while retaining a conservative absence
        # signal for a read-only panel check if the short return text was missed.
        valid, rows, count = self.snapshot()
        scores = [(row, similarity(row.avatar, handle.avatar)) for row in rows]
        matches = [row for row, score in scores if score >= .72]
        candidates = [row for row, score in scores if score >= .65]
        reliable = (valid and count == len(rows) and len(matches) <= 1
                    and len(candidates) == len(matches))
        self._return_missing = (getattr(self, '_return_missing', 0) + 1
                                if reliable and not matches else 0)
        previous = handle.tracker.state
        handle.tracker.observe(visible=bool(matches),
                               status=matches[0].status if len(matches) == 1 else None,
                               reliable=reliable, count_decreased=count < handle.last_count)
        if reliable and len(matches) == 1:
            handle.last_count = count
        if handle.tracker.state != previous:
            self.engine.log(f'第 {handle.queue} 队：{handle.tracker.state}')

    def wait_until_returning(self, handle, timeout=900):
        deadline = time.monotonic() + timeout
        next_diagnostic = time.monotonic() + 10
        self._return_missing = 0
        next_panel_check = 0
        panel_check_failures = 0
        while time.monotonic() < deadline:
            self.check_icon_completion()
            self.poll_return(handle)
            if handle.tracker.state in (MarchState.RETURNING, MarchState.COMPLETED):
                return handle
            if self._return_missing >= 3 and time.monotonic() >= next_panel_check:
                self._return_missing = 0
                next_panel_check = time.monotonic() + 10
                try:
                    confirmed = self.confirm_returned_in_panel(handle)
                except InterruptedError:
                    raise
                except (RuntimeError, TimeoutError) as exc:
                    self.engine.log(f'第 {handle.queue} 队回城复核未完成：{exc}')
                    confirmed = False
                if confirmed:
                    handle.tracker.state = MarchState.COMPLETED
                    self.engine.log(f'第 {handle.queue} 队已连续确认回城空闲，继续下一勾选队列')
                    return handle
                panel_check_failures += 1
                if panel_check_failures >= 3:
                    self.record_panel_failure(self.screenshot())
                    raise RuntimeError(f'第 {handle.queue} 队已消失，但连续三次面板复核未通过；停止以免重复派遣')
            if time.monotonic() >= next_diagnostic:
                self.engine.log(f'伏虎镇伥等待第 {handle.queue} 队进入返回：'
                                f'最后确认状态={handle.tracker.state}，'
                                f'列表诊断={getattr(self, "snapshot_reason", "")}，'
                                f'状态原文={getattr(self, "snapshot_status_texts", [])}')
                next_diagnostic = time.monotonic() + 10
            self.pause(.5)
        self.record_panel_failure(self.screenshot())
        raise TimeoutError(f'第 {handle.queue} 队未确认进入返回状态，停止定位下一只')


def run(engine, case):
    params = case.parameters or {}
    count = attack_count(params.get('attack_count', 1))
    queues = attack_queues(params.get('attack_queues', [1]))
    flow = FuHu(engine)
    flow.allowed_queues = queues
    engine.log(f'伏虎降妖参与队列：{",".join(map(str, queues))}；依次轮转，进入返回状态后继续')
    completed = 0
    try:
        for index in range(count):
            queue = queues[index % len(queues)]
            handle = flow.dispatch_next(queue)
            engine.log(f'第 {handle.queue} 队已出征，等待该队进入返回状态')
            flow.wait_until_returning(handle)
            completed += 1
            engine.log(f'伏虎降妖完成 {completed}/{count} 次（已确认派出队伍进入返回状态）')
    except FuHuFinished as exc:
        engine.log(f'自动伏虎镇伥任务完成：{exc}；停止后续定位和派遣')
        return f'自动伏虎镇伥已完成：任务图标消失（已确认 {completed}/{count} 次进入返回状态）'
    return f'已完成 {count} 次伏虎降妖（已确认各次派遣进入返回状态）'
