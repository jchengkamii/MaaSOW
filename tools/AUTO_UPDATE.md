# GitHub main 自动更新

MaaSOW 使用定制的 MXU 2.4.5。设置 → 脚本自动更新提供启动自动更新开关、立即检查更新和可选下载代理。
更新源为公开仓库 https://github.com/jchengkamii/MaaSOW ，无需 GitHub Token 或 Mirror酱 CDK。

## 工作方式

1. 推送 main 后，`.github/workflows/update.yml` 安装依赖、重新生成 Interface 并运行全部测试。
2. 测试通过后生成 `1.1.<工作流运行序号>` 版本的脚本 ZIP，并创建对应 GitHub Release。
   更新包先上传至草稿，再公开 Release，客户端不会下载未上传完整的包。
3. 客户端启动时检查最新 Release；也可从设置手动检查。
4. 下载完成后等待全部 MXU 任务停止，自动安装、重启；关闭自动检查不会取消已下载的更新。
   程序持续打开时不会定时轮询，请手动检查或下次启动更新。

只发布 `agent/`、`resource/`、环境准备工具和 Interface 等脚本文件。
包内 `interface.json` 带构建版本号，仓库中的版本号无需每次修改。
更新包按目录整体替换，因此能够清理已删除的旧脚本。
`config/`、`cache/`、`debug/`、`.runtime/`、MXU EXE 和 MaaFramework DLL 不在脚本更新包中。
脚本的本地手工修改会被新版本替换；带 `.git` 的开发目录禁止覆盖安装，请使用独立发行目录。
Python 依赖变更后需要重新运行“使用前环境准备.bat”；MXU / MaaFramework 升级需重新分发完整包。

GitHub Actions 需要允许运行工作流及 `contents: write`。构建失败不会发布更新。
没有发布过更新时，GitHub 返回 404，设置页会显示检查失败；首次 main 构建发布成功后即可更新。
修改工作流或推送代码后可在 GitHub Actions 查看 `Publish main script update`。

## 首次启用

普通 MXU 2.4.5 不支持独立 GitHub 版本检查，必须先换成本仓库定制 EXE。
已有旧发行包首次需要手动替换 `九霄小助手.exe` 和包含 `github` 字段的 `interface.json`。
之后脚本更新通过设置页自动完成。

## 重建定制 EXE

需要 Windows x64、Visual Studio C++ 工具、Windows 10/11 SDK、Rust stable、Node 22、pnpm 10.28.0、Python。
也可以运行 GitHub Actions 的 `Build customized MXU`，下载生成的 EXE 并改名为 `九霄小助手.exe`。

```powershell
git clone --depth 1 --branch v2.4.5 https://github.com/MistEO/MXU.git build/mxu-reference
python tools/prepare_mxu.py build/mxu-reference
pnpm --dir build/mxu-reference install --frozen-lockfile
node --experimental-strip-types --test build/mxu-reference/src/services/mainRelease.test.mjs
Set-Location build/mxu-reference
pnpm tauri build --no-bundle
```

产物为 `build/mxu-reference/src-tauri/target/release/mxu.exe`。
构建脚本锁定上游 commit，遇到不匹配版本会拒绝打补丁。
定制代码在 `tools/mxu/`，对上游的适配在 `tools/prepare_mxu.py`。
完整发行包：`python tools/build_distribution.py`。
脚本更新包：`python tools/build_distribution.py --scripts-only --version 1.1.123`。
ZIP 根目录直接包含 `interface.json`，不要额外套一层文件夹。

## 源码与许可证

MXU 基于 AGPL-3.0，许可证见 `licenses/MXU-LICENSE.txt`。
上游源码：https://github.com/MistEO/MXU/tree/115fcb39d75718f8bd53e76511322660b8af00ec
本项目修改与构建说明：https://github.com/jchengkamii/MaaSOW/tree/main/tools
分发定制 EXE 时请保留许可证与上述对应源码信息。
