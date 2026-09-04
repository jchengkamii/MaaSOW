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
3. 根据 `resource/tasks` 重新生成 `resource/interface.tasks.json`。
4. 启动 MXU 前台。

首次进入 MXU 后，选择“九霄仙府游戏窗口”控制器和“九霄仙府测试资源”，
连接已经打开的游戏窗口，再勾选需要执行的任务。

## 项目结构

```text
interface.json                         MXU Project Interface V2 主配置
启动自动化前台.bat                     环境准备与启动入口
requirements.txt                       Python 运行依赖
agent/main.py                          AgentServer 启动入口
agent/core.py                          任务加载、窗口连接和 Maa 执行核心
agent/worker.py                        独立任务工作进程
agent/custom/action/<case_id>/**       复杂用例与 Maa 自定义动作
resource/tasks/<case_id>.json          外部任务清单
resource/base/pipeline/<Domain>/**     按业务域拆分的 Maa Pipeline
resource/base/image/**                 图像识别模板
resource/base/model/**                 OCR 等模型资源
resource/locales/**                    ProjectInterface 展示资源
resource/interface.tasks.json          生成的 ProjectInterface V2 片段
generate_interface.py                  MXU 任务卡片生成器
tests/**                               配置与集成测试
```

## 新增用例

普通 Pipeline 用例通常需要增加或修改：

1. `resource/tasks/<case_id>.json`
2. `resource/base/pipeline/<Domain>/*.json`
3. `resource/base/image/**`

需要循环监视、子进程等复杂行为时，把 Python 文件放在对应的
`agent/custom/action/<case_id>/` 目录，并在任务清单中使用完整模块路径。

修改后重新启动前台即可，不需要重新构建 MXU EXE。

## 自动化流程说明

- MXU 主控制器固定连接“九霄仙府”窗口，右侧预览不会切回微信。
- 每张任务卡片通过 `RunConfiguredCase` 交给 `agent/main.py`。
- Agent 按 case 需要连接微信主窗口、小程序面板或游戏窗口。
- Maa 默认不保存识别绘制图和失败截图。

## 开发与测试

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe .\generate_interface.py
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

GitHub Actions 会在 Windows + Python 3.12 环境中重新生成 MXU Interface，
并运行全部测试。

## 二进制发行包

源码仓库默认不跟踪 `九霄仙府自动化测试.exe` 和 `maafw/`。本地文件不会被删除，
但建议在遵守 MXU 与 MaaFramework 许可证的前提下，将完整运行包通过 GitHub Release
单独发布，避免第三方二进制污染 Git 历史。
