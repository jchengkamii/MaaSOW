# MaaSOW：九霄仙府黑盒自动化测试

本项目基于 MaaFramework 和 MXU（MaaFramework Next UI），用于对微信小游戏
“九霄仙府”执行 Win32 黑盒自动化测试。

## 环境要求

- Windows 10/11
- Python 3.12
- 已安装并登录微信
- 本地运行包中的 `九霄仙府自动化测试.exe` 和 `maafw/`

Python 依赖由 `requirements.txt` 管理，其中固定使用 MaaFw 5.12.3。

## 启动

双击：

```text
启动自动化前台.bat
```

启动脚本会自动：

1. 创建 `.venv` Python 3.12 虚拟环境。
2. 安装 MaaFw Python 依赖。
3. 根据 `cases` 重新生成 `mxu/generated_interface.json`。
4. 启动 MXU 前台。

首次进入 MXU 后，选择“九霄仙府游戏窗口”控制器和“九霄仙府测试资源”，
连接已经打开的游戏窗口，再勾选需要执行的任务。

## 项目结构

```text
interface.json                         MXU Project Interface V2 主配置
启动自动化前台.bat                     环境准备与启动入口
requirements.txt                       Python 运行依赖
app_core.py                            case 加载、窗口连接和 Maa 执行核心
mxu_agent.py                           MXU AgentServer 自定义动作
case_worker.py                         独立 case 工作进程
sync_mxu_interface.py                  cases -> MXU 任务卡片转换器
cases/<case_id>/<case_id>.json         外部用例定义
cases/auto_help/*.py                   自动帮助后台逻辑
resource/pipeline/<case_id>.json       按 case 拆分的 Maa Pipeline
resource/image/**                      图像识别模板
tests/**                               配置与集成测试
```

## 新增用例

普通 Pipeline 用例通常需要增加或修改：

1. `cases/<case_id>/<case_id>.json`
2. `resource/pipeline/<case_id>.json`
3. `resource/image/**`

需要循环监视、子进程等复杂行为时，把 Python 文件放在对应的
`cases/<case_id>/` 目录，并在 case JSON 中使用
`"extension": "cases.<case_id>.<module>:run"`。

修改后重新启动前台即可，不需要重新构建 MXU EXE。

## 自动化流程说明

- MXU 主控制器固定连接“九霄仙府”窗口，右侧预览不会切回微信。
- 每张任务卡片通过 `RunConfiguredCase` 交给 `mxu_agent.py`。
- Agent 按 case 需要连接微信主窗口、小程序面板或游戏窗口。
- “关闭拍脸弹窗”最多处理三轮弹窗，并使用内城左右特征断言主界面。
- “自动帮助”在独立隐藏进程中循环识别，普通 case 执行时自动暂停。
- Maa 默认不保存识别绘制图和失败截图。

## 开发与测试

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe .\sync_mxu_interface.py
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

GitHub Actions 会在 Windows + Python 3.12 环境中重新生成 MXU Interface，
并运行全部测试。

## 二进制发行包

源码仓库默认不跟踪 `九霄仙府自动化测试.exe` 和 `maafw/`。本地文件不会被删除，
但建议在遵守 MXU 与 MaaFramework 许可证的前提下，将完整运行包通过 GitHub Release
单独发布，避免第三方二进制污染 Git 历史。
