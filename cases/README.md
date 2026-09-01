# 外部自动化用例

每个用例使用自己的子目录，目录名、JSON 文件名都与用例 `id` 一致：

```text
cases/
  open_game/
    open_game.json
  auto_help/
    auto_help.json
    auto_help.py
    auto_help_worker.py
```

程序会递归读取 `cases` 下的 `.json` 文件。新增、修改或删除用例后，关闭 MXU
并重新双击 `启动自动化前台.bat` 即可，无需重新打包。

Maa Pipeline 按相同 case ID 拆分在 `resource/pipeline` 中，例如
`cases/open_game/open_game.json` 对应 `resource/pipeline/open_game.json`。
被多个 case 使用的节点可以跨文件引用，Maa 加载资源时会将这些文件合并为统一的节点表。

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

Python 文件放在对应的 case 子目录中，并使用完整模块路径引用。例如：

```json
{
  "id": "auto_help",
  "name": "自动帮助",
  "handler": "python",
  "extension": "cases.auto_help.auto_help:run",
  "parameters": {}
}
```

扩展入口签名：

```python
def run(engine, case):
    return "执行结果说明"
```
