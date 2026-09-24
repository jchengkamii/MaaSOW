import { useState } from 'react';
import { Download } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { autoUpdateEnabled } from '@/services/mainRelease';
import { checkAndPrepareDownload, downloadUpdate, getUpdateSavePath, savePendingUpdateInfo } from '@/services/updateService';
import { createProxySettings } from '@/services/proxyService';
import { DownloadProgressBar } from '../UpdateInfoCard';

export function UpdateSection() {
  const store = useAppStore();
  const [automatic, setAutomatic] = useState(autoUpdateEnabled);
  const [message, setMessage] = useState('');
  const [proxy, setProxy] = useState(store.proxySettings?.url || '');
  const busy = store.updateCheckLoading || store.downloadStatus === 'downloading' || store.installStatus === 'installing';
  const running = store.instances.some((instance) => instance.isRunning);

  async function check() {
    if (busy || !store.projectInterface?.github || !store.projectInterface.version) return;
    const proxySettings = proxy.trim() ? createProxySettings(proxy.trim()) : undefined;
    if (proxy.trim() && !proxySettings) { setMessage('代理格式无效，请使用 http://主机:端口 或 socks5://主机:端口'); return; }
    store.setProxySettings(proxySettings);
    store.setUpdateCheckLoading(true);
    setMessage('正在检查 GitHub main 更新…');
    try {
      const info = await checkAndPrepareDownload({
        resourceId: '', currentVersion: store.projectInterface.version,
        githubUrl: store.projectInterface.github, proxyUrl: proxySettings?.url,
        projectName: store.projectInterface.name,
      });
      if (!info) throw new Error('检查更新失败，请稍后重试');
      store.setUpdateInfo(info);
      if (!info.hasUpdate) { setMessage('当前已是最新版本'); return; }
      if (!info.downloadUrl) throw new Error('更新包尚未就绪');
      store.setDownloadStatus('downloading');
      store.setDownloadProgress({ downloadedSize: 0, totalSize: info.fileSize || 0, speed: 0, progress: 0 });
      const savePath = await getUpdateSavePath(info.filename);
      const result = await downloadUpdate({ url: info.downloadUrl, savePath,
        totalSize: info.fileSize, proxySettings, onProgress: store.setDownloadProgress });
      if (!result.success || !result.actualSavePath) throw new Error('下载失败，请检查网络后重试');
      store.setDownloadSavePath(result.actualSavePath);
      savePendingUpdateInfo({ versionName: info.versionName, releaseNote: info.releaseNote,
        channel: 'main', downloadSavePath: result.actualSavePath, fileSize: info.fileSize,
        updateType: 'full', downloadSource: 'github', timestamp: Date.now() });
      setMessage('下载完成，任务空闲时自动安装并重启');
      store.setDownloadStatus('completed');
    } catch (error) {
      if (useAppStore.getState().downloadStatus === 'downloading') store.setDownloadStatus('failed');
      setMessage(error instanceof Error ? error.message : String(error));
    } finally { store.setUpdateCheckLoading(false); }
  }

  if (!store.projectInterface?.github) return null;
  return (
    <section id="section-update" className="space-y-4 scroll-mt-4">
      <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2"><Download className="w-4 h-4" />脚本自动更新</h2>
      <div className="bg-bg-secondary rounded-xl p-4 border border-border space-y-4">
        <p className="text-sm text-text-secondary">来源：GitHub main · 当前版本 {store.projectInterface.version}</p>
        <label className="flex items-center gap-3 text-sm text-text-primary">
          <input type="checkbox" checked={automatic} onChange={(event) => {
            const enabled = event.target.checked;
            try { localStorage.setItem('maasow-auto-update', String(enabled)); setAutomatic(enabled); }
            catch { setMessage('无法保存自动更新设置'); }
          }} />启动时自动检查并更新
        </label>
        <p className="text-xs text-text-muted">main 推送并通过测试后生成更新包。下载后等待任务结束，再安装并重启；本机配置和 Python 环境保留。</p>
        <label className="block text-sm text-text-secondary">下载代理（可选）
          <input className="mt-2 w-full p-2 rounded-lg bg-bg-tertiary border border-border" value={proxy}
            placeholder="http://127.0.0.1:7890" onChange={(event) => setProxy(event.target.value)}
            onBlur={() => {
              const settings = proxy.trim() ? createProxySettings(proxy.trim()) : undefined;
              if (!proxy.trim() || settings) store.setProxySettings(settings);
              else setMessage('代理格式无效');
            }} />
        </label>
        <button className="px-4 py-2 rounded-lg bg-accent text-white disabled:opacity-50" disabled={busy || store.downloadStatus === 'completed'} onClick={check}>
          {busy ? '正在更新…' : store.downloadStatus === 'completed' ? (running ? '等待任务结束后安装' : '准备安装…') : '立即检查更新'}
        </button>
        {store.downloadStatus === 'downloading' && store.downloadProgress && <DownloadProgressBar downloadStatus={store.downloadStatus} downloadProgress={store.downloadProgress} downloadSource="github" showActions={false} />}
        {store.installStatus === 'failed' && <button className="px-4 py-2 rounded-lg bg-accent text-white disabled:opacity-50" disabled={running} onClick={() => {
          store.resetInstallState(); store.setShowInstallConfirmModal(true); store.setInstallStatus('installing');
        }}>重试安装</button>}
        {message && <p role="status" className="text-sm text-text-secondary">{message}</p>}
      </div>
    </section>
  );
}

