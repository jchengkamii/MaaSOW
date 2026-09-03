# MaaSOW 任务清单

每个任务使用一个 JSON 文件，文件名必须与 `id` 一致。这些清单是 MaaSOW
执行器的配置源，`generate_interface.py` 会校验清单并将启用的任务转换成
ProjectInterface V2 任务卡片。

简单任务使用 `handler: "pipeline"`，复杂业务使用 `handler: "python"` 并通过
`extension` 指向 `agent/custom/action/` 中的 `module:function`。

只有会发起行军且需要展示自动补体开关的任务才设置
`"auto_stamina": true`；未设置时 MXU 任务展开项不会显示该复选项。
