"""Apply the MaaSOW GitHub updater to the pinned upstream MXU source."""
from pathlib import Path
import argparse
import json
import shutil
import subprocess

MXU_REVISION = "115fcb39d75718f8bd53e76511322660b8af00ec"  # v2.4.5
ROOT = Path(__file__).resolve().parents[1]


def prepare(source: Path) -> None:
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != MXU_REVISION:
        raise ValueError(f"Expected MXU {MXU_REVISION}, got {revision}")

    def replace(relative: str, old: str, new: str) -> None:
        path = source / relative
        text = path.read_text(encoding="utf-8-sig")
        if new in text:
            return
        if text.count(old) != 1:
            raise ValueError(f"Unexpected upstream content: {relative}: {old[:80]}")
        path.write_text(text.replace(old, new), encoding="utf-8")

    for relative in ("package.json", "src-tauri/tauri.conf.json"):
        path = source / relative
        config = json.loads(path.read_text(encoding="utf-8"))
        config["version"] = "2.4.5"
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace("src-tauri/Cargo.toml", 'version = "0.1.0"', 'version = "2.4.5"')

    for name in ("mainRelease.ts", "mainUpdate.ts", "mainRelease.test.mjs"):
        shutil.copyfile(ROOT / "tools/mxu" / name, source / "src/services" / name)
    shutil.copyfile(ROOT / "tools/mxu/UpdateSection.tsx", source / "src/components/settings/UpdateSection.tsx")
    replace("src/services/updateService.ts", "// MirrorChyan 更新检查服务",
            "import { checkMainUpdate } from './mainUpdate';\n// MirrorChyan 更新检查服务")
    replace("src/services/updateService.ts",
            "  const { githubUrl, cdk, channel, githubPat, projectName, proxyUrl, ...checkOptions } = options;",
            "  if (options.githubUrl && !options.resourceId) return checkMainUpdate(options);\n\n"
            "  const { githubUrl, cdk, channel, githubPat, projectName, proxyUrl, ...checkOptions } = options;")
    replace("src/services/updateService.ts", "  isInstalling = true;",
            "  if (useAppStore.getState().instances.some((instance) => instance.isRunning)) {\n"
            "    throw new Error('请等待所有任务结束后再安装更新');\n  }\n  isInstalling = true;")
    # Use a separate import, keeping the upstream import blocks intact.
    path = source / "src/App.tsx"
    text = path.read_text(encoding="utf-8")
    if "import { autoUpdateEnabled }" not in text:
        path.write_text("import { autoUpdateEnabled } from '@/services/mainRelease';\n" + text, encoding="utf-8")
    replace("src/App.tsx", "if (result.interface.mirrorchyan_rid && result.interface.version)",
            "if (result.interface.github && result.interface.version && autoUpdateEnabled())")
    replace("src/App.tsx", "resourceId: result.interface.mirrorchyan_rid,", "resourceId: '',")
    replace("src/components/SettingsPage.tsx", "if (projectInterface?.mirrorchyan_rid)", "if (projectInterface?.github)")
    replace("src/components/SettingsPage.tsx", "[projectInterface?.mirrorchyan_rid, settingsSections.length]",
            "[projectInterface?.github, settingsSections.length]")
    replace("src/services/maaService.ts", "const log = loggers.maa;",
            "async function ensureTaskStartAllowed() {\n"
            "  const { useAppStore } = await import('@/stores/appStore');\n"
            "  if (useAppStore.getState().installStatus === 'installing') {\n"
            "    throw new Error('正在安装更新，请等待重启后再运行任务');\n"
            "  }\n}\n\nconst log = loggers.maa;")
    replace("src/services/maaService.ts", "    log.info(\n      '运行任务, 实例:',",
            "    await ensureTaskStartAllowed();\n    log.info(\n      '运行任务, 实例:',")
    replace("src/services/maaService.ts", "    log.info('启动任务, 实例:', instanceId, ', 任务数:', tasks.length, ', cwd:', cwd || '.');",
            "    await ensureTaskStartAllowed();\n    log.info('启动任务, 实例:', instanceId, ', 任务数:', tasks.length, ', cwd:', cwd || '.');")
    replace("src-tauri/src/commands/update.rs",
            '    info!("apply_full_update called");',
            '    if std::path::Path::new(&target_dir).join(".git").exists() {\n'
            '        return Err("开发目录禁止覆盖更新，请在独立发行目录使用自动更新".to_string());\n'
            '    }\n    info!("apply_full_update called");')
    replace("src-tauri/src/commands/download.rs",
            '    let url = format!("https://api.github.com/repos/{}/{}/releases", owner, repo);',
            '    let suffix = if target_version == "latest" { "/latest" } else { "" };\n'
            '    let url = format!("https://api.github.com/repos/{}/{}/releases{}", owner, repo, suffix);')
    replace("src-tauri/src/commands/download.rs", "    let releases: Vec<GitHubRelease> = response",
            '    if target_version == "latest" {\n'
            '        return response.json::<GitHubRelease>().await.map(Some)\n'
            '            .map_err(|e| format!("解析 GitHub 更新失败: {}", e));\n'
            '    }\n\n    let releases: Vec<GitHubRelease> = response')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    prepare(parser.parse_args().source.resolve())

