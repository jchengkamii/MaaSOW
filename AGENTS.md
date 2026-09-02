# MaaSOW 工程约定

本项目遵循 MaaFramework 的 Pipeline v2 与 ProjectInterface V2 协议。

- `resource/base/` 是 Maa Bundle，只放 `pipeline/`、`image/`、`model/` 等框架资源。
- `resource/tasks/` 存放 MaaSOW 任务清单，文件名必须与任务 `id` 一致。
- `agent/custom/action/` 存放具体 Python 业务实现；简单流程优先使用 Pipeline。
- `agent/` 同时负责 Agent 注册、任务加载、生命周期和通用进程适配。
- `resource/interface.tasks.json` 由 `generate_interface.py` 生成，不手工编辑。
- 通用 Pipeline 节点放在 `pipeline/Common/`；功能节点按业务域建目录。
- 图片目录应与 Pipeline 业务域对应，模板路径保持相对于 Bundle 的 `image/`。
- 新增任务后必须重新生成 Interface，并运行全部测试。
