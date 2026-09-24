# 九霄小助手 · MXU macOS

Mac 版使用官方 **MXU 2.6.1** 前端，与 Windows 版采用相同的任务、参数与实时截图界面。框架固定为 MaaFramework 5.12.3。要求 macOS 14+、Python 3.12；支持 Apple Silicon 和 Intel，不需要 Tk。

## 安装与启动

1. 将 `dist/MaaSOW-macOS.zip` 解压到 Mac 可写目录，例如 `~/Applications/MaaSOW-macOS`。
2. 安装 Python 3.12：<https://www.python.org/downloads/macos/>，或使用已有的 Python 3.12。
3. 双击 `使用前环境准备.command`。脚本联网安装 Python 依赖，再从包内 `vendor/` 安装匹配当前 Python 架构的 MXU 与框架库，校验 SHA-256。MXU/框架无需另行下载。不自动安装 Python。
4. 手动登录微信，打开“九霄仙府”，保持游戏已打开且未最小化。
5. 首次运行 `检查环境.command`，按提示为实际运行的 Terminal/Python/MXU 授予屏幕录制、辅助功能权限。授权后重新启动。诊断不会点击游戏。
6. 双击 `启动自动化.command`，进入 MXU，选择“九霄仙府游戏窗口”并连接。在实时截图确认游戏画面，勾选任务、设置参数并开始。

若 .command 无执行权限，可在终端进入目录运行 `bash 使用前环境准备.command`。不要单独移动 `mxu`，需要同目录的 `maafw/`、资源、配置和 Agent。通过启动脚本打开可在退出 MXU 后清理本版本的后台帮助进程。

## 后台执行与鼠标

- MXU 的 Mac 控制器和 Agent/后台帮助的控制器均固定为 **PostToPid**：向目标进程投递输入，不主动移动系统鼠标，不主动激活游戏窗口。
- 使用 **ScreenCaptureKit** 后台截图，游戏不需要保持在最前方。先以普通窗口、同一桌面测试，不要最小化游戏；框架不支持台前调度（Stage Manager）场景。
- 不提供 GlobalEvent 自动回退。旧配置若设为全局输入，会阻止启动或任务连接，不会改用抢鼠标的方式继续执行。
- **Mac 微信能否响应后台事件、是否自行抢焦点，仍需实机验证。** 某些应用可能忽略后台输入或自行激活。若发生无响应/抢焦点，请先在 MXU 停止任务；此版本不会通过前台输入规避。

普通任务使用 MXU 的停止按钮停止。“开启自动帮助”和“停止自动帮助”需要单独执行；MXU 停止普通任务不等于停止已启动的独立帮助。通过 `启动自动化.command` 退出 MXU 时，也会尝试停止帮助进程。

## 配置与排查

- `interface.json`：MXU 的 MacOS / PostToPid 配置、Agent 路径及窗口标题规则。
- `config/macos.json`：Agent 的窗口标题规则；`input_method` 仅允许 PostToPid。修改标题规则时需同步 `interface.json`。
- `config/mxu-runtime.json`：安装器生成的架构、版本和文件校验记录，不随发行包分发。
- `debug/macos_screenshot.png`：诊断截图，短边 720。`debug/auto_help.log`：后台帮助日志。
- 安装器按 **Python 当前运行架构** 选择全部组件，避免混用 ARM 与 Intel 库；建议 M 系列使用原生 ARM Python。
- 如果运行文件损坏、架构或版本发生变化，重新执行环境准备脚本。验证文件不会绕过 macOS 的安全策略。

现有任务与图片模板来自工程快照，不会自动同步 Windows 版后续变化。Mac 画面布局、Retina 缩放差异可能需要模板校准。尚未经过 Mac 真机任务验收，验证范围见 `验证记录.md`。

## 开发与打包

```bash
.venv/bin/python3 generate_interface.py
.venv/bin/python3 -m unittest discover -s tests -v
.venv/bin/python3 tools/package_macos.py
```

`resource/interface.tasks.json` 由生成器维护。打包只包含默认配置，不包含本机 MXU 实例、已安装架构文件和 Python 环境。

官方来源及许可证：
- MXU 2.6.1：<https://github.com/MistEO/MXU/releases/tag/v2.6.1>，AGPL-3.0。
- MaaFramework 5.12.3：<https://github.com/MaaXYZ/MaaFramework/releases/tag/v5.12.3>，LGPL-3.0。
- PostToPid 实现：<https://github.com/MaaXYZ/MaaFramework/blob/v5.12.3/source/MaaMacOSControlUnit/Input/PostToPidInput.mm>。
- 官方控制方式说明：<https://github.com/MaaXYZ/MaaFramework/blob/main/docs/en_us/2.4-ControlMethods.md>。

`vendor/manifest.json` 记录下载地址及官方摘要；原版许可随归档保留，安装时解压至 `licenses/`。
