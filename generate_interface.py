from __future__ import annotations

import json
from pathlib import Path

from agent.core import CaseLoader, PROJECT_DIR

OUTPUT = PROJECT_DIR / "resource" / "interface.tasks.json"
AUTO_STAMINA_OPTION = "自动补体"


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
        if case.auto_stamina:
            task["option"] = [AUTO_STAMINA_OPTION]
        tasks.append(task)

    result = {
        "group": groups,
        "task": tasks,
    }
    if any(case.auto_stamina for case in cases):
        result["option"] = {
            AUTO_STAMINA_OPTION: {
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
        }
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
