# Mac 脚本自动更新与定制 MXU

本目录同步了主工程新增的 MXU 定制源码，锁定上游 v2.4.5 / `115fcb39d75718f8bd53e76511322660b8af00ec`。
Mac 更新器只接受 `MaaSOW-scripts-macos-universal-v<版本>.zip`，不会下载或覆盖安装 Windows 脚本包。

## 当前发行包状态

本次完整包仍内含官方 Mac MXU 2.6.1（Apple Silicon/Intel）。**尚未编译定制 Mac MXU，因此主工程新增的“脚本自动更新”设置页不会随官方二进制直接出现。**
已同步相应前端源码、Mac 包选择逻辑、版本检查测试、Mac 构建及安装脚本。
官方 MXU 可直接运行最新业务任务；要启用定制的自动更新设置页，需在 Mac 上完成下面的构建。

## 在 Mac 上构建定制前端

1. 先运行环境准备脚本，退出 MXU，确保当前 Mac 运行库安装完毕。
2. 安装 Xcode Command Line Tools、Git、Rust stable、Node.js 22+、pnpm 10.28.0。构建脚本只检查依赖，不修改系统工具链。
3. 运行 `构建定制MXU.command`。它在 `build/mxu-custom-v2.4.5` 下载锁定源码，应用本目录补丁，安装前端依赖、运行更新选择测试、编译原生前端。
4. 编译成功且 Mach-O 架构正确后替换 `mxu`，更新本机校验记录；失败不会安装未完成的二进制。重新打开启动脚本即可。

重新运行环境准备脚本会恢复官方 MXU，需要再次运行定制构建脚本切换回来。

## 更新包与发布

```bash
.venv/bin/python3 generate_interface.py
.venv/bin/python3 -m unittest discover -s tests -v
.venv/bin/python3 tools/package_macos.py --scripts-only --version 1.1.123
```

版本号必须与 GitHub Release 标签对应，例如标签 `v1.1.123` 对应 `MaaSOW-scripts-macos-universal-v1.1.123.zip`。
脚本 ZIP 根目录直接包含 interface.json，无外层文件夹；覆盖 agent/resource/tools 与启动文件，保留 config/cache/debug/.venv/vendor/mxu/maafw。
前台在任务结束后安装更新；带 .git 的开发目录禁止覆盖更新。

上游仓库当前发布工作流只生成 Windows 资产。本次没有修改或触发远程发布；发布者需将同版本 Mac 脚本包一起附到 Release。缺少 Mac 资产时，定制更新器会报错停止，不会选择 Windows 资产。
首次自动更新需要先安装定制前端；后续纯脚本更新不包含前端及框架库。Python 依赖变化后需要重新运行环境准备。

更新源：https://github.com/jchengkamii/MaaSOW 。MXU 上游：https://github.com/MistEO/MXU/tree/115fcb39d75718f8bd53e76511322660b8af00ec 。遵循 AGPL-3.0，定制源码与构建方法随本包分发。
