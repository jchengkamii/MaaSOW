"""ROI-first recognition with explicitly enabled full-image fallbacks."""
from __future__ import annotations

from copy import deepcopy
import math

SEARCH_TYPES = {"TemplateMatch", "FeatureMatch", "ColorMatch", "OCR"}
LOCAL_NAME = "__MaaSOW_roi_first__"
FULL_NAME = "__MaaSOW_full_image__"
TREATMENT_HUD_NODES = {
    "自动治疗点击治疗入口", "自动治疗确认正在治疗图标", "自动治疗收取治疗完成",
    "自动治疗确认疑似治疗图标",
    "自动治疗确认未协助", "自动治疗确认已协助",
}
# 面板状态和 HUD 图标均禁止全图兜底，但面板节点并非绿色遮罩图标。
TREATMENT_PANEL_NODES = {
    "自动治疗确认治疗进行中", "自动治疗确认仙盟互助",
}
ROI_ONLY_NODES = TREATMENT_HUD_NODES | TREATMENT_PANEL_NODES


def _inline(recognition: dict, name: str) -> dict:
    return {"sub_name": name, "recognition": recognition}


def _tighten_match(kind: str, params: dict, margin: float) -> None:
    """Use score deltas for normalized methods, relative changes for raw scores."""
    if kind == "TemplateMatch":
        method = params.get("method", 5)

        def tighten(value):
            if method == 0:  # Raw SQDIFF: lower scores are better.
                return value * (1.0 - margin)
            if method == 1:
                return value - min(margin, value / 2.0)
            if method in {3, 5, 10001}:  # Normalized higher-is-better scores.
                return value + min(margin, (1.0 - value) / 2.0)
            # Unnormalized CCORR/CCOEFF scores are not bounded by 1.
            return value + abs(value) * margin

        threshold = params["threshold"]
        params["threshold"] = ([tighten(t) for t in threshold]
                               if isinstance(threshold, list) else tighten(threshold))
    elif kind in {"FeatureMatch", "ColorMatch"} and margin:
        count = params["count"]
        params["count"] = max(count + 1, math.ceil(count * (1.0 + margin)))
        if kind == "FeatureMatch":
            params["ratio"] *= 1.0 - margin


def with_full_image_fallback(recognition: dict, margin: float = 0.0) -> dict:
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
                with_full_image_fallback(child.get("recognition", child), margin),
                child.get("sub_name", child.get("type", "recognition")),
            ) for child in children
        ]
        return result
    if kind not in SEARCH_TYPES:
        return result
    # Relative ROIs carry spatial meaning; never discard their anchor or item row.
    if isinstance(params.get("roi"), str):
        return result
    # Summing unrelated colored pixels across the screen is not a valid fallback.
    if kind == "ColorMatch" and not params.get("connected", False):
        return result
    if params.get("roi", [0, 0, 0, 0]) == [0, 0, 0, 0] and not any(params.get("roi_offset", [0, 0, 0, 0])):
        return result
    full = deepcopy(result)
    full["param"]["roi"] = [0, 0, 0, 0]
    full["param"]["roi_offset"] = [0, 0, 0, 0]
    if kind == "OCR":
        # Full-screen text requires detection; only_rec treats the entire image as one line.
        full["param"]["only_rec"] = False
    else:
        _tighten_match(kind, full["param"], margin)
    return {"type": "Or", "param": {"any_of": [
        _inline(result, LOCAL_NAME), _inline(full, FULL_NAME),
    ]}}


def apply_full_image_fallbacks(resource) -> int:
    overrides = {}
    for name in resource.node_list:
        # Stamina actions depend on the item row. The Fuhu shortcut must stay
        # in the lower-left HUD, away from similar monster faces on the map.
        if name.startswith(("通用自动补体", "伏虎降妖定位")) or name in ROI_ONLY_NODES:
            continue
        data = resource.get_node_data(name)
        if data is None:
            raise RuntimeError(f"无法读取识别节点：{name}")
        policy = data.get("attach", {}).get("full_image_fallback")
        if policy is None:
            continue
        if not isinstance(policy, dict):
            raise ValueError(f"节点 {name} 的 full_image_fallback 必须是对象")
        margin = policy.get("margin", 0.0)
        if (isinstance(margin, bool) or not isinstance(margin, (int, float))
                or not 0 <= margin < 1):
            raise ValueError(f"节点 {name} 的全图兜底 margin 必须在 [0, 1) 内")
        original = data["recognition"]
        replacement = with_full_image_fallback(original, margin)
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
