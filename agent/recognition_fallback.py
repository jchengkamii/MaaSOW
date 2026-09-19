"""ROI-first recognition with a full-image fallback for every loaded task."""
from __future__ import annotations

from copy import deepcopy

SEARCH_TYPES = {"TemplateMatch", "FeatureMatch", "ColorMatch", "OCR",
                "NeuralNetworkClassify", "NeuralNetworkDetect"}
LOCAL_NAME = "__MaaSOW_roi_first__"
FULL_NAME = "__MaaSOW_full_image__"


def _inline(recognition: dict, name: str) -> dict:
    return {"sub_name": name, "recognition": recognition}


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
    return {"type": "Or", "param": {"any_of": [
        _inline(result, LOCAL_NAME), _inline(full, FULL_NAME),
    ]}}


def apply_full_image_fallbacks(resource) -> int:
    overrides = {}
    for name in resource.node_list:
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
