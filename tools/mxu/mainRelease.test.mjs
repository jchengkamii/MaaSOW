import assert from 'node:assert/strict';
import { test } from 'node:test';
import { selectMainUpdate, autoUpdateEnabled } from './mainRelease.ts';
const github = 'https://github.com/jchengkamii/MaaSOW';
const release = (version = '1.1.12') => ({
  tag_name: `v${version}`, body: 'main build', prerelease: false,
  assets: [{ name: `MaaSOW-scripts-win-x86_64-v${version}.zip`, size: 1234,
    browser_download_url: `${github}/releases/download/v${version}/MaaSOW-scripts-win-x86_64-v${version}.zip` }],
});
test('main build newer than bundled version is selected', () => {
  const info = selectMainUpdate(release(), '1.0.1', github);
  assert.equal(info.hasUpdate, true);
  assert.equal(info.versionName, '1.1.12');
  assert.equal(info.updateType, 'full');
});
test('equal and older builds never downgrade', () => {
  for (const current of ['1.1.12', '1.1.13']) {
    const info = selectMainUpdate(release(), current, github);
    assert.equal(info.hasUpdate, false);
    assert.equal(info.downloadUrl, undefined);
  }
});
test('missing, zero size, wrong source, and full packages are rejected', () => {
  for (const mutate of [
    (r) => { r.assets = []; },
    (r) => { r.assets[0].size = 0; },
    (r) => { r.assets[0].browser_download_url = 'https://example.com/update.zip'; },
    (r) => { r.assets[0].name = 'MaaSOW-full-win-x86_64-v1.1.12.zip'; },
  ]) {
    const candidate = release(); mutate(candidate);
    assert.throws(() => selectMainUpdate(candidate, '1.0.1', github));
  }
});
test('invalid version and prereleases are rejected', () => {
  assert.throws(() => selectMainUpdate(release('bad'), '1.0.1', github));
  assert.throws(() => selectMainUpdate(release(), 'bad', github));
  const candidate = release(); candidate.prerelease = true;
  assert.throws(() => selectMainUpdate(candidate, '1.0.1', github));
});
test('automatic check preference defaults on and can be disabled', () => {
  for (const [value, expected] of [[null, true], ['false', false], ['true', true]]) {
    globalThis.localStorage = { getItem: () => value };
    assert.equal(autoUpdateEnabled(), expected);
  }
  delete globalThis.localStorage;
});
