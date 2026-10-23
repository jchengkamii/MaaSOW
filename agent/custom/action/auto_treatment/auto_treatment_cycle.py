from __future__ import annotations

import math
import time

from agent.custom.action.auto_help.automation_mutex import AutomationMutex
from agent.custom.action.auto_treatment.auto_treatment import (
    _click_and_detect_change,
    _run_pipeline,
    _read_treatment_seconds,
    _screenshot,
    _time_exceeds_target,
    _time_reaches_target,
    detect_treatment_rows,
)


def _adjust_and_start_treatment(
    engine,
    controller,
    target_seconds: int,
    click_delay: float,
    recognition_timeout: float,
    max_adjustments: int,
) -> tuple[int, bool, int | None]:
    rows = detect_treatment_rows(_screenshot(controller))
    if not rows:
        raise RuntimeError("愈灵斋中未识别到弟子数量加减按钮")

    adjustments = 0
    known_seconds = _read_treatment_seconds(engine, controller)
    initially_over_target = (
        known_seconds > target_seconds
        if known_seconds is not None
        else _time_exceeds_target(
            engine, recognition_timeout, target_seconds, controller
        )
    )

    # 初始选择过多时，从最后一行向前减少，尽量保留优先级最高的第一行。
    if initially_over_target:
        for row in reversed(rows):
            current_seconds = _read_treatment_seconds(engine, controller)
            if current_seconds is not None:
                known_seconds = current_seconds
            if current_seconds is not None and current_seconds > target_seconds:
                if adjustments >= max_adjustments:
                    raise RuntimeError("自动治疗调整次数超过安全上限")
                adjustments += 1
                changed = _click_and_detect_change(
                    controller, row, row.minus_x, click_delay
                )
                after_probe = _read_treatment_seconds(engine, controller)
                if after_probe is not None:
                    known_seconds = after_probe

                # OCR 时长没有下降时，说明当前行已经减到 0；截图区域的
                # 动画即使产生变化，也不再对这一行重复点击。
                if (
                    after_probe is not None
                    and after_probe >= current_seconds
                ):
                    continue
                if not changed:
                    continue

                if (
                    after_probe is not None
                    and after_probe < current_seconds
                    and after_probe > target_seconds
                ):
                    seconds_per_click = current_seconds - after_probe
                    measured_seconds = after_probe
                    row_exhausted = False
                    while measured_seconds > target_seconds:
                        # 减法使用向上取整，允许最后一次略低于目标；后续会
                        # 按优先级从第一行加回，保持原有的弟子选择策略。
                        estimated_clicks = math.ceil(
                            (measured_seconds - target_seconds)
                            / seconds_per_click
                        )
                        burst_clicks = min(
                            estimated_clicks,
                            max_adjustments - adjustments,
                            100,
                        )
                        if burst_clicks <= 0:
                            raise RuntimeError("自动治疗调整次数超过安全上限")
                        for _ in range(burst_clicks):
                            if not controller.post_click(
                                row.minus_x, row.y
                            ).wait().succeeded:
                                raise RuntimeError(
                                    f"自动治疗快速点击失败：({row.minus_x}, {row.y})"
                                )
                            adjustments += 1
                            time.sleep(0.03)
                        time.sleep(max(0.2, click_delay))
                        calibrated_seconds = _read_treatment_seconds(
                            engine, controller
                        )
                        if calibrated_seconds is None:
                            break
                        known_seconds = calibrated_seconds
                        if calibrated_seconds >= measured_seconds:
                            row_exhausted = True
                            break
                        measured_seconds = calibrated_seconds
                    if measured_seconds <= target_seconds:
                        break
                    if row_exhausted:
                        continue

            # OCR 无法给出有效差值时保留逐次确认兜底。
            while _time_exceeds_target(
                engine, recognition_timeout, target_seconds, controller
            ):
                if adjustments >= max_adjustments:
                    raise RuntimeError("自动治疗调整次数超过安全上限")
                adjustments += 1
                if not _click_and_detect_change(
                    controller, row, row.minus_x, click_delay
                ):
                    break
            if not _time_exceeds_target(
                engine, recognition_timeout, target_seconds, controller
            ):
                break

    # 从第一行开始增加。先用一次点击测量该行单个弟子增加的时长，
    # 距离目标较远时按差值批量快点，随后再用 OCR 校准。
    if known_seconds is None:
        known_seconds = _read_treatment_seconds(engine, controller)
    needs_increase = (
        known_seconds < target_seconds
        if known_seconds is not None
        else not _time_reaches_target(
            engine, recognition_timeout, target_seconds, controller
        )
    )
    if needs_increase:
        for row in rows:
            current_seconds = known_seconds
            if current_seconds is None:
                current_seconds = _read_treatment_seconds(engine, controller)
            if current_seconds is not None:
                known_seconds = current_seconds
            if current_seconds is not None and current_seconds < target_seconds:
                if adjustments >= max_adjustments:
                    raise RuntimeError("自动治疗调整次数超过安全上限")
                adjustments += 1
                changed = _click_and_detect_change(
                    controller, row, row.plus_x, click_delay
                )
                after_probe = _read_treatment_seconds(engine, controller)
                if after_probe is not None:
                    known_seconds = after_probe
                # 数量区域可能因按钮动画产生像素变化；只要 OCR 时长没有
                # 增加，就以时长为准判定该行已经拉满，直接切换下一行。
                if (
                    after_probe is not None
                    and after_probe <= current_seconds
                ):
                    continue
                if not changed:
                    continue
                if after_probe is not None and after_probe >= target_seconds:
                    break
                if (
                    after_probe is not None
                    and after_probe > current_seconds
                    and after_probe < target_seconds
                ):
                    seconds_per_click = after_probe - current_seconds
                    measured_seconds = after_probe
                    row_exhausted = False
                    while measured_seconds < target_seconds:
                        estimated_clicks = math.ceil(
                            (target_seconds - measured_seconds) / seconds_per_click
                        )
                        burst_clicks = min(
                            estimated_clicks,
                            max_adjustments - adjustments,
                            100,
                        )
                        if burst_clicks <= 0:
                            raise RuntimeError("自动治疗调整次数超过安全上限")
                        for _ in range(burst_clicks):
                            if not controller.post_click(row.plus_x, row.y).wait().succeeded:
                                raise RuntimeError(
                                    f"自动治疗快速点击失败：({row.plus_x}, {row.y})"
                                )
                            adjustments += 1
                            time.sleep(0.03)
                        time.sleep(max(0.2, click_delay))
                        calibrated_seconds = _read_treatment_seconds(
                            engine, controller
                        )
                        if calibrated_seconds is None:
                            break
                        known_seconds = calibrated_seconds
                        if calibrated_seconds <= measured_seconds:
                            row_exhausted = True
                            break
                        measured_seconds = calibrated_seconds
                    if measured_seconds >= target_seconds:
                        break
                    if row_exhausted:
                        continue

            # OCR 估算可能遇到按钮已拉满或少量点击未生效，保留原逻辑兜底。
            while not _time_reaches_target(
                engine, recognition_timeout, target_seconds, controller
            ):
                if adjustments >= max_adjustments:
                    raise RuntimeError("自动治疗调整次数超过安全上限")
                adjustments += 1
                if not _click_and_detect_change(controller, row, row.plus_x, click_delay):
                    break
            if _time_reaches_target(
                engine, recognition_timeout, target_seconds, controller
            ):
                break

    final_seconds = _read_treatment_seconds(engine, controller)
    reaches_target = (
        final_seconds >= target_seconds
        if final_seconds is not None
        else _time_reaches_target(
            engine, recognition_timeout, target_seconds, controller
        )
    )
    _click_treatment_with_resource_refill(engine, recognition_timeout)
    return adjustments, reaches_target, final_seconds


def _click_treatment_with_resource_refill(
    engine, recognition_timeout: float
) -> None:
    """开始治疗；资源不足时补充全部并重试。"""
    for attempt in range(4):
        if not _run_pipeline(engine, "自动治疗点击治疗按钮", recognition_timeout):
            raise RuntimeError("未识别到可点击的治疗按钮")
        if not _run_pipeline(engine, "自动治疗资源不足补充全部", 1.2):
            if not (
                _run_pipeline(engine, "自动治疗确认治疗进行中", recognition_timeout)
                or _run_pipeline(engine, "自动治疗确认仙盟互助", recognition_timeout)
            ):
                raise RuntimeError("点击治疗后未确认治疗已开始")
            return
        engine.log("治疗资源不足，已点击补充全部，重新尝试治疗……")
        if attempt == 3:
            raise RuntimeError("补充全部后仍反复出现资源不足提示")


def _adjust_or_reuse_and_start_treatment(
    engine,
    controller,
    target_seconds: int,
    click_delay: float,
    recognition_timeout: float,
    max_adjustments: int,
    previous_seconds: int | None,
    *,
    skip_adjustment: bool = False,
) -> tuple[int, int | None, bool]:
    if skip_adjustment:
        _click_treatment_with_resource_refill(engine, recognition_timeout)
        engine.log("首次弟子数量调节已完成，本批直接开始治疗")
        return 0, previous_seconds, True

    current_seconds = _read_treatment_seconds(engine, controller)
    if previous_seconds is not None and current_seconds == previous_seconds:
        _click_treatment_with_resource_refill(engine, recognition_timeout)
        engine.log(
            f"治疗时间仍为 {current_seconds // 3600:02d}:"
            f"{current_seconds % 3600 // 60:02d}:{current_seconds % 60:02d}，"
            "沿用上次弟子数量"
        )
        return 0, current_seconds, True

    adjustments, _exceeds, final_seconds = _adjust_and_start_treatment(
        engine,
        controller,
        target_seconds,
        click_delay,
        recognition_timeout,
        max_adjustments,
    )
    return adjustments, final_seconds, False


def _resume_help_from_main(engine, recognition_timeout: float) -> bool:
    """治疗面板已退出时交回主循环，由左下角状态决定是否补协助。"""
    if _run_pipeline(engine, "自动治疗确认治疗界面", recognition_timeout):
        return False
    if not _run_pipeline(engine, "自动治疗等待返回主界面", 2.0):
        return False
    engine.log("治疗界面已退出，转为检查左下角未协助、已协助或治疗完成状态")
    return True


def _request_help_and_close(
    engine, recognition_timeout: float, *, require_help: bool
) -> None:
    # 点击成功只代表输入已发送；按钮消失且仍在愈灵斋才算请求已生效。
    # 续接已有治疗也要检查按钮，不能因一次漏识别就直接关闭。
    help_confirmed = False
    for attempt in range(3):
        if _resume_help_from_main(engine, recognition_timeout):
            return
        help_clicked = _run_pipeline(
            engine, "自动治疗点击仙盟互助", recognition_timeout
        )
        if (help_clicked or not require_help) and all(
            _run_pipeline(engine, "自动治疗确认治疗界面", recognition_timeout)
            and not _run_pipeline(engine, "自动治疗确认仙盟互助", 0.8)
            for _ in range(2)
        ):
            help_confirmed = True
            break
        if _resume_help_from_main(engine, recognition_timeout):
            return
        engine.log(f"仙盟互助尚未确认生效，重新检查（{attempt + 1}/3）……")
        _wait_or_stop(engine, 0.5)
    if not help_confirmed:
        raise RuntimeError("重试3次仍未确认仙盟互助生效，且无法交回主界面继续检查")
    for _attempt in range(3):
        _run_pipeline(engine, "自动治疗关闭治疗界面", recognition_timeout)
        if _run_pipeline(engine, "自动治疗等待返回主界面", 2.0) and not _run_pipeline(
            engine, "自动治疗确认治疗界面", 0.8
        ):
            return
    raise RuntimeError("已重试关闭愈灵斋3次，但未确认返回主城或大世界")


def _request_help_from_hud(engine, recognition_timeout: float) -> bool:
    """在主界面补一次协助；返回是否仍在治疗，不打开愈灵斋。"""
    if not _run_pipeline(engine, "自动治疗点击未协助图标", recognition_timeout):
        raise RuntimeError("未协助图标点击失败，未确认请求协助")
    engine.log("检测到未协助状态，已点击一次左下角图标，等待确认已协助……")
    for _attempt in range(3):
        _wait_or_stop(engine, 0.5)
        if _run_pipeline(engine, "自动治疗确认已协助", recognition_timeout) and not _run_pipeline(
            engine, "自动治疗确认未协助", recognition_timeout
        ):
            engine.log("已确认切换为已协助状态，继续等待治疗完成")
            return True
        # 请求协助后若本批立即完成，收取结果并交回主循环检查剩余伤兵。
        if _run_pipeline(engine, "自动治疗收取治疗完成", recognition_timeout):
            return False
    raise RuntimeError("已点击一次未协助图标，但未确认变为已协助或治疗完成，停止重复点击")


def _wait_or_stop(engine, seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if engine.stop_event.is_set():
            raise InterruptedError("用户停止执行")
        time.sleep(min(0.5, deadline - time.monotonic()))


def run(engine, case) -> str:
    parameters = case.parameters or {}
    target_seconds = int(parameters.get("target_seconds", 1800))
    click_delay = max(0.2, float(parameters.get("click_delay", 0.4)))
    recognition_timeout = max(
        0.5, float(parameters.get("recognition_timeout", 1.5))
    )
    max_adjustments = max(1, int(parameters.get("max_adjustments", 2000)))
    poll_interval = max(1.0, float(parameters.get("poll_interval", 2.0)))
    empty_confirmations = max(2, int(parameters.get("empty_confirmations", 3)))

    controller = engine._controller_for("game")
    total_adjustments = 0
    treatment_batches = 0
    reused_batches = 0
    previous_treatment_seconds: int | None = None
    # 游戏会记忆上一批选择的弟子数量。本次任务首次遇到可治疗面板时
    # 调节一次，后续批次直接开始治疗，不再截图识别加减按钮或 OCR 时间。
    selection_adjusted = False
    # 收取一批不代表伤兵已全部治完。后续仍需检查入口，低分的疑似
    # 图标也不能计为“无图标”，避免入口颜色或背景变化导致提前结束。
    active_treatment = False

    # 初始导航保持原子性，避免自动帮助在中间插入点击。
    with AutomationMutex():
        if not _run_pipeline(engine, "自动治疗确认治疗界面", recognition_timeout) and not _run_pipeline(
            engine, "自动治疗返回主城或大世界", 45.0
        ):
            raise RuntimeError("无法返回主城或大世界")

    empty_hits = 0
    unknown_hits = 0
    waiting_logged = False
    while True:
        if engine.stop_event.is_set():
            raise InterruptedError("用户停止执行")
        wait_seconds = 0.0
        # 每轮状态判断及其后续点击作为一个短原子操作；退出 with 后立刻
        # 释放跨进程锁，治疗等待期间自动帮助即可继续识别和点击。
        with AutomationMutex():
            # 等待中也检查愈灵斋，处理界面未关掉或意外重新打开的情况。
            if _run_pipeline(engine, "自动治疗确认治疗界面", recognition_timeout):
                empty_hits = 0
                unknown_hits = 0
                waiting_logged = False
                running = _run_pipeline(
                    engine, "自动治疗确认治疗进行中", recognition_timeout
                ) or _run_pipeline(engine, "自动治疗确认仙盟互助", recognition_timeout)
                if not running:
                    adjustments, previous_treatment_seconds, reused = _adjust_or_reuse_and_start_treatment(
                        engine,
                        controller,
                        target_seconds,
                        click_delay,
                        recognition_timeout,
                        max_adjustments,
                        previous_treatment_seconds,
                        skip_adjustment=selection_adjusted,
                    )
                    selection_adjusted = True
                    total_adjustments += adjustments
                    treatment_batches += 1
                    reused_batches += int(reused)
                active_treatment = True
                _request_help_and_close(
                    engine, recognition_timeout, require_help=not running
                )
            elif _run_pipeline(engine, "自动治疗收取治疗完成", recognition_timeout):
                active_treatment = False
                empty_hits = 0
                unknown_hits = 0
                waiting_logged = False
                wait_seconds = click_delay
            elif _run_pipeline(engine, "自动治疗确认未协助", recognition_timeout):
                active_treatment = _request_help_from_hud(engine, recognition_timeout)
                empty_hits = 0
                unknown_hits = 0
                waiting_logged = False
                wait_seconds = poll_interval if active_treatment else click_delay
            elif _run_pipeline(engine, "自动治疗点击治疗入口", recognition_timeout):
                empty_hits = 0
                unknown_hits = 0
                waiting_logged = False
                if not _run_pipeline(engine, "自动治疗等待治疗界面", 12.0):
                    raise RuntimeError("点击治疗入口后没有进入愈灵斋")
            elif _run_pipeline(engine, "自动治疗确认已协助", recognition_timeout):
                active_treatment = True
                empty_hits = 0
                unknown_hits = 0
                if not waiting_logged:
                    engine.log("弟子已协助，正在治疗中，等待治疗完成……")
                    waiting_logged = True
                wait_seconds = poll_interval
            else:
                on_main_screen = _run_pipeline(
                    engine, "自动治疗确认内城", recognition_timeout
                ) or _run_pipeline(
                    engine, "自动治疗确认大世界", recognition_timeout
                )
                uncertain_icon = on_main_screen and _run_pipeline(
                    engine, "自动治疗确认疑似治疗图标", recognition_timeout
                )
                if active_treatment or not on_main_screen or uncertain_icon:
                    empty_hits = 0
                    unknown_hits += 1
                    reason = "存在疑似治疗图标" if uncertain_icon else "左下角治疗状态未确认"
                    engine.log(f"{reason}（连续 {unknown_hits} 次），重新检查界面……")
                    if unknown_hits >= 6:
                        raise RuntimeError("恢复主界面后仍无法识别左下角治疗状态，停止等待，请检查游戏界面")
                    if unknown_hits >= 3:
                        if not _run_pipeline(engine, "自动治疗返回主城或大世界", 45.0):
                            raise RuntimeError("治疗状态丢失，且无法恢复主城或大世界")
                    wait_seconds = min(2.0, poll_interval)
                else:
                    unknown_hits = 0
                    empty_hits += 1
                    if empty_hits >= empty_confirmations:
                        return (
                            "自动治疗完成；"
                            f"共开始 {treatment_batches} 批治疗，"
                            f"调整弟子数量 {total_adjustments} 次，"
                            f"沿用上次治疗数量 {reused_batches} 批"
                        )
                    wait_seconds = min(2.0, poll_interval)
        if wait_seconds > 0:
            _wait_or_stop(engine, wait_seconds)
