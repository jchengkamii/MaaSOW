"""ROI-first recognition with a full-image fallback for every loaded task."""
from __future__ import annotations

from copy import deepcopy

SEARCH_TYPES = {"TemplateMatch", "FeatureMatch", "ColorMatch", "OCR",
                "NeuralNetworkClassify", "NeuralNetworkDetect"}
LOCAL_NAME = "__MaaSOW_roi_first__"
FULL_NAME = "__MaaSOW_full_image__"
# 全图兜底只在匹配分比 ROI 阈值高出该裕量时才接受，避免 ROI 内未命中时，
# 兜底把画面里相似的无关元素（如弟子行的深色横条）误判成命中。像素相似度
# 匹配对跨机器的显卡/DPI/色温差异敏感，裕量越大越保守、越不容易误报。
FULL_IMAGE_MARGIN = 0.08
TREATMENT_HUD_NODES = {
    "自动治疗点击治疗入口", "自动治疗确认正在治疗图标", "自动治疗收取治疗完成",
    "自动治疗确认疑似治疗图标",
    "自动治疗确认未协助", "自动治疗确认已协助",
    # 愈灵斋内的状态节点必须固定在自身 ROI 内识别，全图兜底会把弟子行的
    # 深色横条误判成“治疗进行中”，导致界面一打开就被关闭。
    "自动治疗确认治疗进行中", "自动治疗确认仙盟互助",
}


def _inline(recognition: dict, name: str) -> dict:
    return {"sub_name": name, "recognition": recognition}


def _raise_threshold(params: dict, margin: float) -> None:
    """提高 threshold 以收紧匹配；threshold 可为单值或多模板数组。"""
    threshold = params.get("threshold")
    if isinstance(threshold, (int, float)):
        params["threshold"] = round(min(1.0, threshold + margin), 4)
    elif isinstance(threshold, list):
        params["threshold"] = [round(min(1.0, t + margin), 4) for t in threshold]


def with_full_image_fallback(recognition: dict) -> dict:
    """Accept Resource.get_node_data's normalized v2 recognition definition."""
    result = deepcopy(recognition)
    kind = result["type"]
    params = result["param"]
    if kind in {"And", "Or"}:
        key = "all_of" if kind == "And" else "any_of"
        children = params[key]
        # Already wrapped: don't turn a second application into nested fallbacks.
        if (kind == "Or" and len(children) == 2
                and isinstance(children[0], dict)
                and children[0].get("sub_name") == LOCAL_NAME):
            return result
        params[key] = [
            child if isinstance(child, str) else _inline(
                with_full_image_fallback(child.get("recognition", child)),
                child.get("sub_name", child.get("type", "recognition")),
            ) for child in children
        ]
        return result
    if kind not in SEARCH_TYPES:
        return result
    if params.get("roi", [0, 0, 0, 0]) == [0, 0, 0, 0] and not any(params.get("roi_offset", [0, 0, 0, 0])):
        return result
    full = deepcopy(result)
    full["param"]["roi"] = [0, 0, 0, 0]
    full["param"]["roi_offset"] = [0, 0, 0, 0]
    if kind == "OCR":
        # Full-screen text requires detection; only_rec treats the entire image as one line.
        full["param"]["only_rec"] = False
    elif kind in {"TemplateMatch", "FeatureMatch", "ColorMatch"}:
        _raise_threshold(full["param"], FULL_IMAGE_MARGIN)
    return {"type": "Or", "param": {"any_of": [
        _inline(result, LOCAL_NAME), _inline(full, FULL_NAME),
    ]}}


def apply_full_image_fallbacks(resource) -> int:
    overrides = {}
    for name in resource.node_list:
        # Stamina actions depend on the item row. The Fuhu shortcut must stay
        # in the lower-left HUD, away from similar monster faces on the map.
        # Treatment's three states also depend on the lower-left HUD location.
        if name.startswith(("通用自动补体", "伏虎降妖定位")) or name in TREATMENT_HUD_NODES:
            continue
        data = resource.get_node_data(name)
        if data is None:
            raise RuntimeError(f"无法读取识别节点：{name}")
        original = data["recognition"]
        replacement = with_full_image_fallback(original)
        if replacement != original:
            overrides[name] = {"recognition": replacement}
    if overrides and not resource.override_pipeline(overrides):
        raise RuntimeError("应用全图搜索兜底失败")
    return len(overrides)


def recognition_candidates(detail):
    """Read nested Or/And results, preferring matched branches over rejected text."""
    values = [detail.best_result, *detail.filtered_results, *detail.all_results]
    seen = set()
    for value in values:
        if value is None or id(value) in seen:
            continue
        seen.add(id(value))
        children = getattr(value, "sub_results", None)
        if children is not None:
            hits = [child for child in children if child.hit]
            for child in hits or children:
                yield from recognition_candidates(child)
        else:
            yield value
