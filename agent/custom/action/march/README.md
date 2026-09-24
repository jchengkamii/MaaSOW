# 通用行军单元

由业务功能决定目标；通用单元不搜索怪物或玩家，不自动调节弟子数量。
复用已有大世界、内城识别和返回模板，进入大地图后点击目标。

```python
from agent.custom.action.march.march import March

# 调用方持有 AutomationMutex（普通 case 的 worker 已持有）。
march = March(engine)
handle = march.dispatch(target=(360, 600), queue=2)
march.wait(handle, timeout=900, poll_interval=0.5)
```

target 使用 Maa 归一化截图坐标。需要业务导航时可用
`march.dispatch(None, queue=1, select_target=lambda engine: ...)`；
回调在确认大地图后执行，负责选择目标并打开环形菜单。
队列编号 1–4，省略时使用气泡指向的当前队列；锁、月卡及无法确认编号的槽位不点击。
一键上阵只点击一次，重新识别出征按钮后派遣。

`dispatch` 返回已确认出征的句柄；`poll(handle)` 单次判断完成；
`wait(handle)` 等待完成或超时。可以保存多个句柄轮询，不要并发操作同一游戏 UI。
兼容 case 的入口为 `agent.custom.action.march.march:run`，参数为
`target: [x, y]`、`queue: 1..4`（可省略）、`timeout: 900`、`poll_interval: 0.5`。
当前是公共单元，未添加缺少目标配置的前台任务。

仅从小队行上半部分 OCR 前往、战斗中、返回，倒计时不进入状态 OCR 图片。
按头像跟踪队伍，列表重排不改变身份。先看到返回，再连续 3 次确认头像消失、
队列数减少才结束；列表收起、遮挡、识别失败和头像歧义不会判为结束。
点击出征后未确认队伍会报错，不重放出征；体力不足等弹窗由调用方处理。
同头像队伍不能区分时保守等待，超时报错。适用项目短边 720 的竖屏布局。

行军使用独立的 `model/ocr/march_zh` 中文模型；保留原有英文数字模型。
源模型来自同级 MaaFramework 测试资源，来源见模型目录 README。
出征前会读取已有小队，拒绝与所选队伍同头像的已有行军，防止把旧队列当成新出征。

已经打开出征面板时，可用 `handle = march.dispatch_from_panel(queue=1)` 直接续接，
随后调用 `march.wait(handle)`。若调用方有出征前小队快照，可传 `existing=rows` 检查头像冲突。
进攻菜单使用文字定位后匹配上方红色图标，点击图标而非文字。
