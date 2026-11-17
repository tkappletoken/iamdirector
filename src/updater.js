'use strict';
const { app, BrowserWindow, dialog } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const up = require('./update-policy');

let updater = null;
let timer = null;
let manual = false;
const asked = new Set();
let downloadedVersion = null;

function configured() {
  return up.enabled({ isPackaged: app.isPackaged, platform: process.platform, env: process.env })
    && fs.existsSync(path.join(process.resourcesPath, 'app-update.yml'));
}

function blockedReason() {
  return up.selfUpdateBlocked({
    platform: process.platform,
    exePath: app.getPath('exe'),
    inApplications: process.platform === 'darwin' && app.isInApplicationsFolder(),
  });
}

let moveAsked = false;
async function promptMove(isManual) {
  if (moveAsked && !isManual) return;
  moveAsked = true;
  const canMove = typeof app.moveToApplicationsFolder === 'function';
  const r = await box({
    type: 'info', title: '無法自動更新',
    message: '請先把「我是導演」拖進「應用程式」再開啟，才能自動更新',
    detail: '現在是從下載的磁碟映像檔或「下載項目」直接開啟，macOS 不允許這樣執行的 app 更新自己。'
      + (canMove ? '\n按「幫我移過去」會把 app 搬到「應用程式」並重新開啟。' : ''),
    buttons: canMove ? ['幫我移過去', '稍後'] : ['好'], defaultId: 0, cancelId: canMove ? 1 : 0,
  });
  if (!canMove || r.response !== 0) return;
  try {
    if (!app.moveToApplicationsFolder()) throw new Error('not moved');
  } catch (_) {
    box({ type: 'warning', title: '沒有搬成', message: '沒辦法自動搬移',
      detail: '請關掉「我是導演」，在 Finder 把它拖進「應用程式」，再從「應用程式」開啟。', buttons: ['好'] });
  }
}

function box(opts) {
  const w = BrowserWindow.getFocusedWindow() || BrowserWindow.getAllWindows()[0];
  return w ? dialog.showMessageBox(w, opts) : dialog.showMessageBox(opts);
}

function load(getSettings) {
  if (updater) return updater;
  const { autoUpdater } = require('electron-updater');
  autoUpdater.autoDownload = false;
  autoUpdater.allowPrerelease = up.allowPrerelease(getSettings());
  autoUpdater.allowDowngrade = false;
  autoUpdater.autoInstallOnAppQuit = getSettings().autoInstallOnQuit !== false;
  autoUpdater.logger = null;

  autoUpdater.on('update-available', async (info) => {
    const kind = up.classify(app.getVersion(), info.version);
    if (!kind) return;
    if (downloadedVersion === info.version) { if (manual) promptRestart(info.version); return; }
    if (kind === 'patch') {
      if (manual) box({ type: 'info', title: '有新版本', message: `正在下載 ${info.version}`, detail: '下載完成後會問你要不要重新啟動。', buttons: ['好'] });
      autoUpdater.downloadUpdate().catch(() => {});
      return;
    }
    if (asked.has(info.version) && !manual) return;
    asked.add(info.version);
    const r = await box({
      type: 'info', title: '有新版本',
      message: `「我是導演」${info.version} 已經推出`,
      detail: `目前版本 ${app.getVersion()}。要現在下載嗎？下載完成後會再問你要不要重新啟動。`,
      buttons: ['下載', '稍後'], defaultId: 0, cancelId: 1,
    });
    if (r.response === 0) autoUpdater.downloadUpdate().catch(() => {});
  });

  autoUpdater.on('update-not-available', () => {
    if (manual) box({ type: 'info', title: '檢查更新', message: '已是最新版本', detail: `目前版本 ${app.getVersion()}`, buttons: ['好'] });
  });

  autoUpdater.on('update-downloaded', (info) => {
    downloadedVersion = info.version;
    promptRestart(info.version);
  });

  autoUpdater.on('error', () => { });

  updater = autoUpdater;
  return updater;
}

const restartAsked = new Set();
async function promptRestart(version) {
  if (restartAsked.has(version) && !manual) return;
  restartAsked.add(version);
  const onQuit = updater.autoInstallOnAppQuit;
  const r = await box({
    type: 'info', title: '新版本已下載',
    message: `「我是導演」${version} 已經下載好了`,
    detail: onQuit ? '要現在重新啟動套用嗎？選「稍後」的話，下次結束 app 時會自動安裝。'
      : '要現在重新啟動套用嗎？',
    buttons: ['重新啟動', '稍後'], defaultId: 0, cancelId: 1,
  });
  if (r.response === 0) setImmediate(() => updater.quitAndInstall());
}

function check(isManual) {
  manual = isManual;
  return updater.checkForUpdates()
    .catch((err) => {
      if (isManual) box({ type: 'warning', title: '檢查更新', message: '檢查更新失敗', detail: '連不到更新伺服器，請確認網路連線後再試一次。', buttons: ['好'] });
      return err;
    })
    .finally(() => { manual = false; });
}

function start(getSettings) {
  if (!configured()) return;
  if (blockedReason()) { setTimeout(() => promptMove(false), up.FIRST_CHECK_MS); return; }
  load(getSettings);
  setTimeout(() => check(false), up.FIRST_CHECK_MS);
  timer = setInterval(() => check(false), up.CHECK_EVERY_MS);
  timer.unref?.();
}

function checkNow(getSettings) {
  if (!configured()) return;
  if (blockedReason()) { promptMove(true); return; }
  load(getSettings);
  check(true);
}

function setAutoInstallOnQuit(on) {
  if (updater) updater.autoInstallOnAppQuit = !!on;
}

module.exports = { configured, start, checkNow, setAutoInstallOnQuit };
