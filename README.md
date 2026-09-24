# 九霄小助手

基于 MaaFramework 和 MXU，用于微信小游戏“九霄仙府”的自动化测试。

## 使用

支持 Windows 10 1809 及以上的 Windows 10/11 x64。

1. clone 仓库或完整解压发行包。
2. 首次运行“使用前环境准备.bat”，保持联网，等待提示 `Environment ready`。
3. 登录微信并打开“九霄仙府”，双击“九霄小助手.exe”。
4. 选择游戏窗口控制器和测试资源，连接窗口后勾选任务并运行。

以后直接打开 EXE 即可；环境异常时重新运行环境准备脚本。请勿单独移动 EXE。

## 开发

使用 Python 3.12：

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe .\generate_interface.py
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

工程约定见 [AGENTS.md](AGENTS.md)，第三方许可证见 [licenses/](licenses/)。

## 自动更新

定制 MXU 的“设置 → 脚本自动更新”支持启动检查及手动更新。
每次推送 main 并通过 GitHub Actions 测试后，自动发布脚本更新包；客户端在任务结束后安装并重启。
本机配置与 Python 环境保留。开发 Git 目录禁止覆盖安装，请在独立发行目录使用。
首次需要使用定制 EXE，构建和发布方法见 [自动更新说明](tools/AUTO_UPDATE.md)。
