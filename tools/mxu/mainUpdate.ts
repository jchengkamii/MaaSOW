import { exists } from '@tauri-apps/plugin-fs';
import { useAppStore } from '@/stores/appStore';
import { joinPath } from '@/utils/paths';
import { invoke } from '@tauri-apps/api/core';
import { selectMainUpdate, type MainRelease } from './mainRelease';

export async function checkMainUpdate(options: {
  githubUrl?: string; currentVersion: string; githubPat?: string; proxyUrl?: string;
}) {
  const basePath = useAppStore.getState().basePath;
  if (basePath && await exists(joinPath(basePath, '.git'))) {
    throw new Error('开发目录禁止覆盖更新，请在独立发行目录使用自动更新');
  }
  const match = options.githubUrl?.match(/^https:\/\/github\.com\/([\w-]+)\/([\w.-]+)\/?$/);
  if (!match) throw new Error('GitHub 仓库地址无效');
  const release = await invoke<MainRelease | null>('get_github_release_by_version', {
    owner: match[1], repo: match[2], targetVersion: 'latest',
    githubPat: options.githubPat, proxyUrl: options.proxyUrl,
  });
  if (!release) throw new Error('尚未发布 main 更新包');
  return selectMainUpdate(release, options.currentVersion, options.githubUrl!);
}
