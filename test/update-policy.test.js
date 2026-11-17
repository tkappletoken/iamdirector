'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const up = require('../src/update-policy');

test('只在打包版啟用；Linux 只有 AppImage，deb 不啟用', () => {
  assert.equal(up.enabled({ isPackaged: true, platform: 'darwin', env: {} }), true);
  assert.equal(up.enabled({ isPackaged: true, platform: 'win32', env: {} }), true);
  assert.equal(up.enabled({ isPackaged: true, platform: 'linux', env: { APPIMAGE: '/home/u/iamdirector.AppImage' } }), true);
  assert.equal(up.enabled({ isPackaged: true, platform: 'linux', env: {} }), false, 'deb');
  assert.equal(up.enabled({ isPackaged: true, platform: 'linux', env: { APPIMAGE: '' } }), false);
  for (const platform of ['darwin', 'win32', 'linux']) {
    assert.equal(up.enabled({ isPackaged: false, platform, env: { APPIMAGE: '/x' } }), false, `dev ${platform}`);
  }
  assert.equal(up.enabled({ isPackaged: true, platform: 'freebsd', env: {} }), false);
});

test('patch 版背景下載；minor、major 先問', () => {
  assert.equal(up.classify('0.1.5', '0.1.6'), 'patch');
  assert.equal(up.classify('0.1.5', '0.1.10'), 'patch');
  assert.equal(up.classify('0.1.5', '0.2.0'), 'major');
  assert.equal(up.classify('0.1.5', '1.0.0'), 'major');
  assert.equal(up.classify('1.9.9', '2.0.0'), 'major');
});

test('不是比較新、或看不懂的版本號：不理', () => {
  for (const [a, b] of [['0.1.5', '0.1.5'], ['0.1.6', '0.1.5'], ['0.2.0', '0.1.9'], ['0.1.5', 'garbage'], ['x', '0.1.6'], ['0.1.5', '']]) {
    assert.equal(up.classify(a, b), null, `${a} → ${b}`);
  }
});

test('預發佈版不默默裝：一律先問', () => {
  assert.equal(up.classify('0.1.5', '0.1.6-beta.1'), 'major');
  assert.equal(up.classify('0.1.6-beta.1', '0.1.6'), 'major');
  assert.equal(up.classify('0.1.6', '0.1.6-beta.1'), null);
});

test('prerelease 只認 settings.json 的布林值 true', () => {
  assert.equal(up.allowPrerelease({ updatePrerelease: true }), true);
  for (const s of [{}, null, undefined, { updatePrerelease: 'true' }, { updatePrerelease: 1 }, { updatePrerelease: false }, { updatePrerelease: {} }]) {
    assert.equal(up.allowPrerelease(s), false, JSON.stringify(s));
  }
});

test('檢查節奏：啟動 5 秒、之後每 30 分鐘', () => {
  assert.equal(up.FIRST_CHECK_MS, 5000);
  assert.equal(up.CHECK_EVERY_MS, 30 * 60 * 1000);
});

test('selfUpdateBlocked：Mac 從 dmg／下載項目開（translocation）或不在應用程式就不自己更新', () => {
  const T = '/private/var/folders/9m/x/T/AppTranslocation/C888F8DD/d/我是導演.app/Contents/MacOS/我是導演';
  assert.equal(up.selfUpdateBlocked({ platform: 'darwin', exePath: T, inApplications: false }), 'translocated');
  assert.equal(up.selfUpdateBlocked({ platform: 'darwin', exePath: T, inApplications: true }), 'translocated', 'translocation 優先');
  assert.equal(up.selfUpdateBlocked({ platform: 'darwin', exePath: '/Volumes/我是導演 0.1.7/我是導演.app/Contents/MacOS/我是導演', inApplications: false }), 'not-in-applications');
  assert.equal(up.selfUpdateBlocked({ platform: 'darwin', exePath: '/Applications/我是導演.app/Contents/MacOS/我是導演', inApplications: true }), null);
  assert.equal(up.selfUpdateBlocked({ platform: 'win32', exePath: 'C:\\x\\iamdirector.exe', inApplications: false }), null);
  assert.equal(up.selfUpdateBlocked({ platform: 'linux', exePath: '/tmp/.mount_x/iamdirector', inApplications: false }), null);
});
