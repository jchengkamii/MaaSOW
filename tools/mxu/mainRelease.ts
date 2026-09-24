import * as semver from 'semver';

export interface MainRelease {
  tag_name: string;
  body: string;
  prerelease: boolean;
  assets: { name: string; size: number; browser_download_url: string }[];
}

// A unique release per successful main build prevents cached/partially replaced packages.
export function selectMainUpdate(release: MainRelease, currentVersion: string, githubUrl: string) {
  const version = semver.valid(release.tag_name);
  const current = semver.valid(currentVersion);
  if (!version || !current || release.prerelease) throw new Error('更新版本信息无效');
  const hasUpdate = semver.gt(version, current);
  const filename = `MaaSOW-scripts-win-x86_64-v${version}.zip`;
  const asset = release.assets.find((item) => item.name === filename);
  const expected = `${githubUrl.replace(/\/$/, '')}/releases/download/${release.tag_name}/${filename}`;
  if (hasUpdate && (!asset || asset.size <= 0 || asset.browser_download_url !== expected)) {
    throw new Error('此版本缺少完整的 Windows 脚本更新包，请等待 GitHub 构建完成');
  }
  return {
    hasUpdate, versionName: version, releaseNote: release.body || '',
    filename, fileSize: asset?.size,
    downloadUrl: hasUpdate ? asset?.browser_download_url : undefined,
    downloadSource: 'github' as const, updateType: 'full' as const, channel: 'main',
  };
}

export function autoUpdateEnabled(): boolean {
  try { return localStorage.getItem('maasow-auto-update') !== 'false'; }
  catch { return true; }
}
