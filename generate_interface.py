from __future__ import annotations

import json
from pathlib import Path

from agent.core import CaseLoader, PROJECT_DIR

OUTPUT = PROJECT_DIR / "resource" / "interface.tasks.json"
AUTO_STAMINA_OPTION = "自动补体"
TREATMENT_DURATION_OPTION = "自动治疗时长"


def generate() -> dict:
    cases = [case for case in CaseLoader().load() if case.enabled]
    group_ids: dict[str, str] = {}
    groups: list[dict] = []
    for case in cases:
        if case.group not in group_ids:
            group_id = f"group_{len(group_ids) + 1:02d}"
            group_ids[case.group] = group_id
            groups.append(
                {
                    "name": group_id,
                    "label": case.group,
                    "default_expand": True,
                }
            )

    tasks = []
    for case in cases:
        task = {
            "name": case.id,
            "label": case.name,
            "entry": "MXU执行外部用例",
            "default_check": case.default_checked,
            "description": case.description,
            "group": [group_ids[case.group]],
            "controller": ["WeChatOrGame"],
            "resource": ["Default"],
            "pipeline_override": {
                "MXU执行外部用例": {
                    "custom_action_param": {"case_id": case.id}
                }
            },
        }
        task_options = []
        if case.auto_stamina:
            task_options.append(AUTO_STAMINA_OPTION)
        if case.id == "auto_treatment":
            task_options.append(TREATMENT_DURATION_OPTION)
        if task_options:
            task["option"] = task_options
        tasks.append(task)

    result = {
        "group": groups,
        "task": tasks,
    }
    options = {}
    if any(case.auto_stamina for case in cases):
        options[AUTO_STAMINA_OPTION] = {
            "type": "checkbox",
            "label": "",
            "default_case": [],
            "cases": [
                {
                    "name": "自动补体",
                    "label": "自动补体",
                    "pipeline_override": {
                        "通用自动补体开关": {"enabled": True}
                    },
                }
            ],
        }
    if any(case.id == "auto_treatment" for case in cases):
        options[TREATMENT_DURATION_OPTION] = {
            "type": "input",
            "label": "",
            "description": "设置每批治疗的目标时长（分钟）",
            "inputs": [
                {
                    "name": "目标分钟",
                    "label": "分钟",
                    "description": "请输入 1–10000 的整数，默认 30 分钟",
                    "default": "30",
                    "pipeline_type": "int",
                    "verify": "^(?:[1-9]\\d{0,3}|10000)$",
                    "pattern_msg": "请输入 1–10000 的整数",
                }
            ],
            "pipeline_override": {
                "MXU执行外部用例": {
                    "custom_action_param": {
                        "case_id": "auto_treatment",
                        "target_minutes": "{目标分钟}",
                    }
                }
            },
        }
    if options:
        result["option"] = options
    return result


def main() -> int:
    data = generate()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"已生成 MXU Interface：{len(data['group'])} 个分组，"
        f"{len(data['task'])} 个用例 -> {OUTPUT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
