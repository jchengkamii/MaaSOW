# 外部自动化用例

`agent/custom/action/` 用于需要 Python 扩展的复杂业务。每个扩展使用自己的子目录：

```text
agent/custom/action/
  auto_help/
    auto_help.py
    auto_help_worker.py
```

任务清单统一放在 `resource/tasks/<case_id>.json`。程序会递归读取该目录；
新增、修改或删除任务后，关闭 MXU 并重新双击 `启动自动化前台.bat` 即可，
无需重新打包。

Maa Pipeline 按业务域拆分在 `resource/base/pipeline` 中，例如自动雷达位于
`resource/base/pipeline/AutoRadar/`。
被多个 case 使用的节点可以跨文件引用，Maa 加载资源时会将这些文件合并为统一的节点表。
通用场景与控件节点应放入 `resource/base/pipeline/Common/`，避免功能之间反向依赖。

## Maa Pipeline 用例

```json
{
  "version": 1,
  "id": "unique_case_id",
  "name": "显示名称",
  "group": "用例分组",
  "description": "用例说明",
  "order": 100,
  "default_checked": false,
  "enabled": true,
  "handler": "pipeline",
  "controller_target": "game",
  "pipeline_entry": "Pipeline入口名称"
}
```

`controller_target` 可选值：

- `wechat_main`：微信主窗口
- `wechat_panel`：微信小程序面板
- `game`：九霄仙府窗口

可选字段：

- `skip_if_window_exists`：目标窗口已存在时直接判定通过。
- `wait_for_window`：Pipeline 完成后等待指定窗口出现。
- `wait_timeout`：等待窗口的秒数，默认 30。
- `postcondition_entry`：窗口出现后必须执行成功的 Maa Pipeline 断言。
- `postcondition_target`：执行后置断言的窗口目标。
- `postcondition_timeout`：从打开目标窗口开始计算的后置断言总等待秒数。

## Python 扩展用例

Python 文件放在对应的 action 子目录中，并使用完整模块路径引用。例如：

```json
{
  "id": "auto_help",
  "name": "自动帮助",
  "handler": "python",
  "extension": "agent.custom.action.auto_help.auto_help:run",
  "parameters": {}
}
```

扩展入口签名：

```python
def run(engine, case):
    return "执行结果说明"
```

## 识别范围兼容配置

全图兜底由 Pipeline 节点的 `attach.full_image_fallback` 显式启用；未配置的节点保持原 ROI。
例如：

```json
"attach": {"full_image_fallback": {"margin": 0.08}}
```

`margin` 范围为 `[0, 1)`，默认 `0`，仅收紧兜底分支，不改变区域内识别。
归一化模板匹配按分数方向调整阈值，接近 0/1 时最多使用剩余空间的一半；
非归一化模板分数按比例调整。特征匹配提高 `count` 并降低 `ratio`，
连通颜色匹配提高 `count`；非连通颜色统计和神经网络识别不自动扩大范围。

字符串 ROI（节点或锚点引用）始终保留相对范围。物品行、治疗 HUD 与治疗面板状态
也禁止全图兜底，避免跨行、跨界面误识别。治疗时长读数、补充全部和关闭治疗面板
保持局部识别，避免读取其他计时器或在固定点击目标之外确认按钮。
治疗面板状态先在同一帧识别标题，再相对标题查找“治疗进行中”和“仙盟互助”，
不依赖前一个 Tasker 的缓存。标题模板为 170×65，状态区域的偏移覆盖了标题在原搜索框
`[230, 110, 260, 120]` 内时的原有状态 ROI，并随面板整体位移。

修改通用识别策略或 Pipeline 时，应同步 `_Mac/` 对应文件，并运行两份基础测试。
