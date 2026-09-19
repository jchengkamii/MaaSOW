# MaaSOW：九霄仙府黑盒自动化测试

本项目基于 MaaFramework 和 MXU（MaaFramework Next UI），用于对微信小游戏
“九霄仙府”执行 Win32 黑盒自动化测试。

## 使用与环境准备

支持 Windows 10 1809 及以上的 Windows 10/11 x64，微信需自行安装登录。

首次双击“使用前环境准备.bat”，脚本检测环境，
缺少时联网下载官方 Python 3.12.10 嵌入版、pip、requirements.txt 依赖、
VC++ 与 WebView2。Python 位于项目 .runtime/python/，与系统环境隔离。
Python 压缩包校验 SHA256，微软安装程序校验数字签名。

随后双击“九霄仙府自动化测试.exe”打开前台。
环境异常时重新运行环境准备脚本，已满足时不重复下载。支持中文、空格目录；PowerShell 脚本使用 UTF-8 BOM，
批处理内容使用 ASCII，Python 输出固定为 UTF-8。
VC++ 安装可能弹出 Windows 授权提示，安装要求重启时应重启后重新准备。

首次进入 MXU 后，选择游戏窗口控制器和测试资源，
连接已经打开的游戏窗口，再勾选需要执行的任务。

## 项目结构

```text
interface.json                         MXU Project Interface V2 主配置
使用前环境准备.bat                     联网检测和安装环境
九霄仙府自动化测试.exe                 前台唯一启动入口
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

## 打包分发

先完成环境准备，再运行：

    & ./.runtime/python/python.exe -X utf8 ./tools/build_distribution.py

脚本重新生成 Interface、运行全部测试，以白名单复制必要文件，
输出 dist/release-1.0.0.zip。
压缩包包含前台、maafw、资源、Agent、环境准备入口、说明和第三方许可；
不含 .venv、.runtime、Git、IDE、截图原图、缓存、日志和个人配置。
接收者完整解压后运行“使用前环境准备.bat”，联网准备一次后直接打开 EXE。
打包流程不会修改当前用户配置。

九霄仙府自动化测试.exe、maafw/ 为本机已有的第三方二进制，
源码仓库不跟踪；重新构建分发包前须自行准备这些文件。
