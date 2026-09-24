# 九霄小助手 使用说明

适用：Windows 10 1809 或更新的 Windows 10/11，x64。

1. 完整解压到本地可写目录，支持中文和空格路径。
2. 首次双击“使用前环境准备.bat”，保持联网。
3. 显示 Environment ready 后，双击“九霄小助手.exe”。
4. 登录微信，打开九霄仙府，选择游戏窗口控制器、测试资源，连接后选择任务。

环境准备检测原生 DLL、WebView2 和项目专用 Python。缺少组件才联网下载：
微软官方 VC++ / WebView2、python.org Python 3.12.10 嵌入版、
bootstrap.pypa.io pip，以及 PyPI 上的 requirements.txt 依赖。
Python 只放在本目录 .runtime，不修改系统 PATH，不依赖作者的 .venv。
VC++ 安装可能出现 Windows 管理员授权提示；若要求重启，请重启后再运行准备脚本。
下载失败会显示错误，恢复联网后可重新运行；保留正常证书校验。
以后直接打开 EXE。环境异常时重新运行环境准备脚本，已满足时不重复下载。

请勿单独移动 EXE，勿在 ZIP 内直接运行。不要放在网络共享、只读目录或过深目录；
建议解压路径小于 80 个字符。微信与游戏需自行准备登录。
日志在 debug/；运行后的 config、cache、debug 为本机数据，重新分发前应排除。
组织策略禁止 PowerShell 或阻止下载时请联系管理员；脚本不修改全局执行策略。

组件来源：
- MXU 2.4.5：https://github.com/MistEO/MXU/tree/v2.4.5 （AGPL-3.0）
- MaaFramework 5.12.3：https://github.com/MaaXYZ/MaaFramework/tree/v5.12.3
- 许可证见 licenses/ 与 maafw/MaaAgentBinary/LICENSE，转发时保留。
