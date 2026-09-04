from __future__ import annotations

import time
import re
from dataclasses import dataclass

import numpy as np
from maa.tasker import Tasker


@dataclass(frozen=True)
class TreatmentRow:
    minus_x: int
    plus_x: int
    y: int


def _run_pipeline(engine, entry: str, timeout: float) -> bool:
    """执行一个短 Pipeline 断言；未命中属于正常分支。"""
    try:
        with engine._state_lock:
            resource = engine._resource
        if resource is None:
            engine.reload_resources()
            with engine._state_lock:
                resource = engine._resource
        if resource is None:
            raise RuntimeError("Maa Resource 未初始化")
        engine._execute_pipeline_entry(
            "game", entry, resource, timeout_override=max(0.2, timeout)
        )
        return True
    except RuntimeError:
        return False


def _screenshot(controller) -> np.ndarray:
    image = controller.post_screencap().wait().get()
    if image is None or image.size == 0:
        raise RuntimeError("自动治疗截图为空")
    return image


def _contiguous_ranges(values: np.ndarray) -> list[tuple[int, int]]:
    indexes = np.flatnonzero(values)
    if indexes.size == 0:
        return []
    breaks = np.flatnonzero(np.diff(indexes) > 1)
    starts = np.r_[indexes[0], indexes[breaks + 1]]
    ends = np.r_[indexes[breaks], indexes[-1]]
    return [(int(start), int(end)) for start, end in zip(starts, ends)]


def detect_treatment_rows(image: np.ndarray) -> list[TreatmentRow]:
    """按蓝色加号的纵坐标发现当前可见行，返回顺序即治疗优先级。"""
    height, width = image.shape[:2]
    x1, x2 = int(width * 0.66), int(width * 0.77)
    y1, y2 = int(height * 0.33), int(height * 0.72)
    roi = image[y1:y2, x1:x2]
    if roi.size == 0:
        return []

    blue, green, red = (roi[:, :, index] for index in range(3))
    blue_mask = (
        (blue > 135)
        & (green > 75)
        & (red < 135)
        & ((blue.astype(np.int16) - red.astype(np.int16)) > 55)
    )
    rows = []
    # 圆形按钮在多条相邻扫描线上均有大量蓝色像素；文字和细线不会通过。
    for start, end in _contiguous_ranges(blue_mask.sum(axis=1) >= 8):
        if end - start + 1 < 18:
            continue
        local = blue_mask[start : end + 1]
        ys, xs = np.nonzero(local)
        if xs.size < 180:
            continue
        plus_x = x1 + int(np.median(xs))
        center_y = y1 + start + int(np.median(ys))
        minus_x = max(0, plus_x - int(width * 0.40))
        rows.append(TreatmentRow(minus_x=minus_x, plus_x=plus_x, y=center_y))

    # 同一按钮可能因高光被分成相邻块，合并纵向距离很近的结果。
    merged: list[TreatmentRow] = []
    for row in sorted(rows, key=lambda item: item.y):
        if merged and row.y - merged[-1].y < 35:
            previous = merged[-1]
            merged[-1] = TreatmentRow(
                minus_x=(previous.minus_x + row.minus_x) // 2,
                plus_x=(previous.plus_x + row.plus_x) // 2,
                y=(previous.y + row.y) // 2,
            )
        else:
            merged.append(row)
    return merged


def _count_crop(image: np.ndarray, row: TreatmentRow) -> np.ndarray:
    height, width = image.shape[:2]
    x1 = min(width, row.plus_x + int(width * 0.045))
    x2 = min(width, row.plus_x + int(width * 0.225))
    y1 = max(0, row.y - 30)
    y2 = min(height, row.y + 30)
    return image[y1:y2, x1:x2].copy()


def _crop_changed(before: np.ndarray, after: np.ndarray) -> bool:
    if before.shape != after.shape or before.size == 0:
        return True
    delta = np.abs(before.astype(np.int16) - after.astype(np.int16))
    changed_pixels = np.count_nonzero(np.max(delta, axis=2) >= 18)
    return changed_pixels / before.shape[0] / before.shape[1] >= 0.002


def _click_and_detect_change(
    controller, row: TreatmentRow, x: int, click_delay: float
) -> bool:
    before_image = _screenshot(controller)
    before = _count_crop(before_image, row)
    if not controller.post_click(x, row.y).wait().succeeded:
        raise RuntimeError(f"自动治疗点击失败：({x}, {row.y})")
    time.sleep(click_delay)
    after = _count_crop(_screenshot(controller), row)
    return _crop_changed(before, after)


def _time_exceeds_target(
    engine, timeout: float, target_seconds: int, controller=None
) -> bool:
    if controller is not None:
        seconds = _read_treatment_seconds(engine, controller)
        if seconds is not None:
            return seconds > target_seconds
    if target_seconds != 1800:
        raise RuntimeError("无法读取治疗时间，不能判断自定义治疗目标")
    return _run_pipeline(engine, "自动治疗时间超过30分钟", timeout)


def _time_reaches_target(
    engine, timeout: float, target_seconds: int, controller=None
) -> bool:
    if controller is not None:
        seconds = _read_treatment_seconds(engine, controller)
        if seconds is not None:
            return seconds >= target_seconds
    if target_seconds != 1800:
        raise RuntimeError("无法读取治疗时间，不能判断自定义治疗目标")
    return _run_pipeline(engine, "自动治疗时间达到30分钟", timeout)


def _parse_treatment_seconds(text: str) -> int | None:
    normalized = text.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "：": ":", ";": ":"}))
    # 超过 24 小时时游戏显示“2天 01:06:06”。OCR 也可能漏掉“天”字，
    # 变成“2 01:06:06”，两种形式都必须先按天数解析。
    day_match = re.search(
        r"(?<!\d)(\d{1,3})(?:\s*天\s*|\s+)(\d{1,2}):([0-5]\d):([0-5]\d)(?!\d)",
        normalized,
    )
    if day_match:
        days, hours, minutes, seconds = (
            int(value) for value in day_match.groups()
        )
        if hours < 24:
            return days * 86400 + hours * 3600 + minutes * 60 + seconds

    match = re.search(
        r"(?<!\d)(\d{1,3}):([0-5]\d):([0-5]\d)(?!\d)", normalized
    )
    if not match:
        # Maa 偶尔会漏识别小时与分钟之间的冒号，例如把
        # 00:29:23 识别成 0029:23。
        match = re.search(
            r"(?<!\d)(\d{1,3})([0-5]\d):([0-5]\d)(?!\d)", normalized
        )
    if not match:
        return None
    hours, minutes, seconds = (int(value) for value in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _read_treatment_seconds(engine, controller) -> int | None:
    """使用 Maa OCR 节点读取治疗按钮上的动态时长。"""
    with engine._state_lock:
        resource = engine._resource
    if resource is None:
        engine.reload_resources()
        with engine._state_lock:
            resource = engine._resource
    if resource is None:
        raise RuntimeError("Maa Resource 未初始化")

    tasker = Tasker()
    tasker.bind(resource, controller)
    if not tasker.inited:
        raise RuntimeError("Maa Tasker 初始化失败")

    with engine._state_lock:
        engine._current_tasker = tasker
    try:
        job = tasker.post_task("自动治疗读取时间").wait()
        if engine.stop_event.is_set():
            raise InterruptedError("用户停止执行")
        detail = job.get()
        if detail is None:
            return None
        for node in reversed(detail.nodes):
            recognition = node.recognition
            if recognition is None:
                continue
            # 即使 expected 因图标噪声未命中，all_results 中通常仍有可用
            # OCR 文本，因此不能只依赖 job.succeeded / filtered_results。
            candidates = [
                recognition.best_result,
                *recognition.filtered_results,
                *recognition.all_results,
            ]
            for candidate in candidates:
                text = getattr(candidate, "text", None)
                if text and (seconds := _parse_treatment_seconds(text)) is not None:
                    return seconds
        return None
    finally:
        with engine._state_lock:
            if engine._current_tasker is tasker:
                engine._current_tasker = None


def run(engine, case) -> str:
    parameters = case.parameters or {}
    target_seconds = int(parameters.get("target_seconds", 1800))
    click_delay = max(0.2, float(parameters.get("click_delay", 0.4)))
    recognition_timeout = max(
        0.5, float(parameters.get("recognition_timeout", 1.5))
    )
    max_adjustments = max(1, int(parameters.get("max_adjustments", 2000)))

    controller = engine._controller_for("game")
    if not _run_pipeline(engine, "自动治疗确认治疗界面", recognition_timeout):
        if not _run_pipeline(engine, "自动治疗返回主城或大世界", 45.0):
            raise RuntimeError("无法返回主城或大世界")
        if not _run_pipeline(engine, "自动治疗点击治疗入口", recognition_timeout):
            return "当前没有可治疗弟子"
        if not _run_pipeline(engine, "自动治疗等待治疗界面", 12.0):
            raise RuntimeError("点击治疗入口后没有进入愈灵斋")

    rows = detect_treatment_rows(_screenshot(controller))
    if not rows:
        raise RuntimeError("愈灵斋中未识别到弟子数量加减按钮")

    adjustments = 0
    initially_over_target = _time_exceeds_target(
        engine, recognition_timeout, target_seconds, controller
    )

    # 初始选择过多时，从最后一行向前减少，尽量保留优先级最高的第一行。
    if initially_over_target:
        for row in reversed(rows):
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

    # 从第一行开始逐个增加；一行拉满后自动转到下一行。
    if not _time_reaches_target(
        engine, recognition_timeout, target_seconds, controller
    ):
        for row in rows:
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

    reaches_target = _time_reaches_target(
        engine, recognition_timeout, target_seconds, controller
    )
    if not _run_pipeline(engine, "自动治疗点击治疗按钮", recognition_timeout):
        raise RuntimeError("未识别到可点击的治疗按钮")

    target_minutes = target_seconds / 60
    target_label = (
        f"{int(target_minutes)}分钟"
        if target_minutes.is_integer()
        else f"{target_minutes:g}分钟"
    )
    if reaches_target:
        return f"已调整 {adjustments} 次并开始治疗，治疗时间达到{target_label}"
    return (
        f"全部弟子治疗时间不足{target_label}，"
        f"已拉满并开始治疗（调整 {adjustments} 次）"
    )
