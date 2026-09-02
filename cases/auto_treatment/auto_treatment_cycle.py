from __future__ import annotations

import time

from cases.auto_treatment.auto_treatment import (
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
    initially_over_target = _time_exceeds_target(
        engine, recognition_timeout, target_seconds
    )

    # 初始选择过多时，从最后一行向前减少，尽量保留优先级最高的第一行。
    if initially_over_target:
        for row in reversed(rows):
            while _time_exceeds_target(engine, recognition_timeout, target_seconds):
                if adjustments >= max_adjustments:
                    raise RuntimeError("自动治疗调整次数超过安全上限")
                adjustments += 1
                if not _click_and_detect_change(
                    controller, row, row.minus_x, click_delay
                ):
                    break
            if not _time_exceeds_target(engine, recognition_timeout, target_seconds):
                break

    # 从第一行开始逐个增加；一行拉满后自动转到下一行。
    if not _time_reaches_target(engine, recognition_timeout, target_seconds):
        for row in rows:
            while not _time_reaches_target(
                engine, recognition_timeout, target_seconds
            ):
                if adjustments >= max_adjustments:
                    raise RuntimeError("自动治疗调整次数超过安全上限")
                adjustments += 1
                if not _click_and_detect_change(controller, row, row.plus_x, click_delay):
                    break
            if _time_reaches_target(engine, recognition_timeout, target_seconds):
                break

    reaches_target = _time_reaches_target(
        engine, recognition_timeout, target_seconds
    )
    final_seconds = _read_treatment_seconds(engine, controller)
    if not _run_pipeline(engine, "自动治疗点击治疗按钮", recognition_timeout):
        raise RuntimeError("未识别到可点击的治疗按钮")
    return adjustments, reaches_target, final_seconds


def _adjust_or_reuse_and_start_treatment(
    engine,
    controller,
    target_seconds: int,
    click_delay: float,
    recognition_timeout: float,
    max_adjustments: int,
    previous_seconds: int | None,
) -> tuple[int, int | None, bool]:
    current_seconds = _read_treatment_seconds(engine, controller)
    if previous_seconds is not None and current_seconds == previous_seconds:
        if not _run_pipeline(engine, "自动治疗点击治疗按钮", recognition_timeout):
            raise RuntimeError("未识别到可点击的治疗按钮")
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


def _request_help_and_close(
    engine, recognition_timeout: float, *, require_help: bool
) -> None:
    help_clicked = _run_pipeline(
        engine, "自动治疗点击仙盟互助", recognition_timeout
    )
    # 新开始的治疗必须成功请求互助；续接既有治疗时按钮可能已经点过。
    if require_help and not help_clicked:
        raise RuntimeError("治疗开始后未识别到仙盟互助按钮")
    for _attempt in range(3):
        if not _run_pipeline(engine, "自动治疗关闭治疗界面", recognition_timeout):
            raise RuntimeError("治疗开始后未识别到愈灵斋关闭按钮")
        _wait_or_stop(engine, 0.7)
        if not _run_pipeline(engine, "自动治疗确认治疗界面", 0.8):
            return
    raise RuntimeError("已重试关闭愈灵斋3次，但治疗界面仍然存在")


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
    poll_interval = max(1.0, float(parameters.get("poll_interval", 10.0)))
    empty_confirmations = max(2, int(parameters.get("empty_confirmations", 3)))

    controller = engine._controller_for("game")
    total_adjustments = 0
    treatment_batches = 0
    reused_batches = 0
    previous_treatment_seconds: int | None = None
    # 一旦开始或接管了一批治疗，必须等到明确点击“治疗完成”图标后，
    # 才允许用“连续无治疗图标”判定整个流程完成。
    active_treatment = False

    # 最优先判断愈灵斋；若已处于治疗中，直接续接互助和关闭流程。
    if _run_pipeline(engine, "自动治疗确认治疗界面", recognition_timeout):
        if _run_pipeline(engine, "自动治疗确认治疗进行中", recognition_timeout):
            active_treatment = True
            _request_help_and_close(
                engine, recognition_timeout, require_help=False
            )
        else:
            adjustments, previous_treatment_seconds, reused = _adjust_or_reuse_and_start_treatment(
                engine,
                controller,
                target_seconds,
                click_delay,
                recognition_timeout,
                max_adjustments,
                previous_treatment_seconds,
            )
            total_adjustments += adjustments
            treatment_batches += 1
            reused_batches += int(reused)
            active_treatment = True
            _request_help_and_close(engine, recognition_timeout, require_help=True)
    elif not _run_pipeline(engine, "自动治疗返回主城或大世界", 45.0):
        raise RuntimeError("无法返回主城或大世界")

    empty_hits = 0
    waiting_logged = False
    while True:
        if engine.stop_event.is_set():
            raise InterruptedError("用户停止执行")

        # 治疗完成图标优先处理，收取后立即重新判断。
        if _run_pipeline(engine, "自动治疗收取治疗完成", recognition_timeout):
            active_treatment = False
            empty_hits = 0
            waiting_logged = False
            _wait_or_stop(engine, click_delay)
            continue

        # 红色十字表示仍有伤兵，开始下一批治疗。
        if _run_pipeline(engine, "自动治疗点击治疗入口", recognition_timeout):
            empty_hits = 0
            waiting_logged = False
            if not _run_pipeline(engine, "自动治疗等待治疗界面", 12.0):
                raise RuntimeError("点击治疗入口后没有进入愈灵斋")
            adjustments, previous_treatment_seconds, reused = _adjust_or_reuse_and_start_treatment(
                engine,
                controller,
                target_seconds,
                click_delay,
                recognition_timeout,
                max_adjustments,
                previous_treatment_seconds,
            )
            total_adjustments += adjustments
            treatment_batches += 1
            reused_batches += int(reused)
            active_treatment = True
            _request_help_and_close(engine, recognition_timeout, require_help=True)
            continue

        # 绿色十字表示治疗尚未结束，保持任务运行并定时复查。
        if _run_pipeline(engine, "自动治疗确认正在治疗图标", recognition_timeout):
            active_treatment = True
            empty_hits = 0
            if not waiting_logged:
                engine.log("弟子正在治疗中，等待治疗完成……")
                waiting_logged = True
            _wait_or_stop(engine, poll_interval)
            continue

        # 已开始的治疗尚未明确收取时，短暂识别不到任何状态图标只能等待，
        # 不能把它当成“所有治疗已完成”。
        if active_treatment:
            empty_hits = 0
            if not waiting_logged:
                engine.log("治疗状态图标暂未识别，继续等待治疗完成……")
                waiting_logged = True
            _wait_or_stop(engine, poll_interval)
            continue

        # 无治疗批次待收取时，也必须确认当前确实位于主城或大世界，
        # 避免加载动画、弹窗或其他界面造成三个模板同时漏识别。
        on_main_screen = _run_pipeline(
            engine, "自动治疗确认内城", recognition_timeout
        ) or _run_pipeline(engine, "自动治疗确认大世界", recognition_timeout)
        if not on_main_screen:
            empty_hits = 0
            _wait_or_stop(engine, min(2.0, poll_interval))
            continue

        # 防止界面切换的一帧空白导致提前结束，连续多次无图标才算完成。
        empty_hits += 1
        if empty_hits >= empty_confirmations:
            return (
                "自动治疗完成；"
                f"共开始 {treatment_batches} 批治疗，调整弟子数量 {total_adjustments} 次，"
                f"沿用上次治疗数量 {reused_batches} 批"
            )
        _wait_or_stop(engine, min(2.0, poll_interval))
