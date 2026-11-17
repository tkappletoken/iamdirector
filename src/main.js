'use strict';
const path = require('node:path');
const fs = require('node:fs');
const {
  app, BrowserWindow, Menu, Notification, dialog, ipcMain, net, safeStorage, screen, session, shell,
} = require('electron');
const { spawn } = require('node:child_process');
const policy = require('./policy');
const menu = require('./menu');
const settings = require('./settings');
const updater = require('./updater');
const devport = require('./devport');
const windowBounds = require('./window-bounds');
const extLogin = require('./external-login');
const localPage = require('./local-page');
const keystoreMod = require('./keystore');
const localServer = require('./local-server');
const modeMod = require('./mode');
const cloudSync = require('./cloud-sync');
const openh264 = require('./openh264');

let START_URL = policy.startUrl(process.env);
let MODE = 'cloud';
let localSrv = null;
const DEV = !app.isPackaged;
const PARTITION = 'persist:iamdirector';

let win = null;
let lastUrl = null;

function trace(ev, data) {
  const f = process.env.IAMDIRECTOR_TRACE;
  if (!f) return;
  try { fs.appendFileSync(f, JSON.stringify({ t: new Date().toISOString(), ev, ...data }) + '\n'); } catch (_) {}
}

const dbg = devport.apply({ isPackaged: app.isPackaged, env: process.env, commandLine: app.commandLine });
if (dbg.refused) {
  console.error('打包版不提供除錯埠，已拒絕命令列參數：' + dbg.present.join(', '));
  app.exit(1);
}
const udSuffix = devport.devUserDataSuffix({ isPackaged: app.isPackaged });
if (udSuffix) app.setPath('userData', app.getPath('userData') + udSuffix);

app.commandLine.appendSwitch('lang', 'zh-TW');

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', (_e, argv) => {
    const link = extLogin.findProtocolArg(argv);
    if (link) { onProtocolUrl(link); return; }
    bringToFront();
  });
}

if (process.defaultApp && process.argv.length >= 2) {
  app.setAsDefaultProtocolClient(extLogin.PROTOCOL, process.execPath, [path.resolve(process.argv[1])]);
} else {
  app.setAsDefaultProtocolClient(extLogin.PROTOCOL);
}
app.on('open-url', (e, url) => { e.preventDefault(); onProtocolUrl(url); });

const pendingLogin = extLogin.createPending();
let localKind = null;

app.userAgentFallback = app.userAgentFallback.split(' ')
  .filter((t) => !t.startsWith('Electron/') && !t.startsWith(app.getName() + '/')
    && !t.startsWith('iamdirector-desktop/'))
  .join(' ');

function createWindow() {
  const s = settings.get();
  const display = Number.isFinite(s.bounds?.x) && Number.isFinite(s.bounds?.y) && s.bounds.width > 0 && s.bounds.height > 0
    ? screen.getDisplayMatching(s.bounds) : screen.getPrimaryDisplay();
  const b = windowBounds.fitBounds(s.bounds, display.workArea);
  win = new BrowserWindow({
    ...b,
    title: '我是導演',
    backgroundColor: '#0b0b0f',
    show: false,
    webPreferences: {
      partition: PARTITION,
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      nodeIntegrationInSubFrames: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      spellcheck: false,
      navigateOnDragDrop: false,
    },
  });
  if (s.maximized) win.maximize();
  win.once('ready-to-show', () => win.show());

  const saveBounds = () => {
    if (!win || win.isDestroyed()) return;
    settings.set({ bounds: win.getNormalBounds(), maximized: win.isMaximized() });
  };
  win.on('resize', debounce(saveBounds, 500));
  win.on('move', debounce(saveBounds, 500));
  win.on('close', saveBounds);
  win.on('close', () => {
    const u = win.webContents.getURL();
    lastUrl = policy.isRestorableUrl(u, START_URL) ? u : null;
    trace('remember-url', { saved: !!lastUrl });
  });
  win.on('closed', () => { win = null; });
  win.on('focus', () => win.flashFrame(false));

  guardContents(win.webContents);
  win.webContents.on('will-prevent-unload', (event) => {
    const n = liveJobs; liveJobs = 0;
    const r = dialog.showMessageBoxSync(win, {
      type: 'warning', buttons: ['等完成', '仍要結束'], defaultId: 0, cancelId: 0,
      title: '還有工作在生成',
      message: n > 0 ? `還有 ${n} 件在生成，確定要結束？` : '還有工作在生成，確定要結束？',
      detail: '結束後這幾件仍會在 AppleToken 那邊跑完、照樣計費；下次打開會接著顯示結果。',
    });
    trace('prevent-unload', { live: n, quit: r === 1 });
    if (r === 1) event.preventDefault();
    else quitting = false;
  });

  win.webContents.on('did-fail-load', (_e, code, desc, url, isMain) => {
    if (!isMain || code === -3) return;
    showOffline(policy.isRestorableUrl(url, START_URL) ? url : START_URL, String(desc || code));
  });
  win.webContents.on('did-navigate', (_e, url) => {
    if (/^https?:/.test(url)) { localKind = null; stopOfflinePoll(); }
  });
  win.on('closed', stopOfflinePoll);

  const first = lastUrl && policy.isRestorableUrl(lastUrl, START_URL) ? lastUrl : START_URL;
  trace('load-start', { restored: first !== START_URL });
  win.loadURL(first);
}

function guardContents(wc) {
  const onNav = (e, url) => {
    const provider = extLogin.loginProvider(url, (u) => policy.isAppUrl(u, START_URL));
    if (provider) { e.preventDefault(); startExternalLogin(provider, url); return; }
    if (localKind === 'wait') pendingLogin.cancel();
    if (policy.isAllowedNavigation(url, START_URL)) return;
    e.preventDefault();
    if (url.startsWith('file:')) return;
    trace('blocked-navigation', { url, external: policy.isSafeExternal(url) });
    if (policy.isSafeExternal(url)) shell.openExternal(url);
  };
  wc.on('will-navigate', onNav);
  wc.on('will-redirect', onNav);
  wc.on('will-frame-navigate', (e) => {
    if (!e.isMainFrame && !policy.isAllowedNavigation(e.url, START_URL) && !e.url.startsWith('about:')
        && !e.url.startsWith('blob:') && !e.url.startsWith('data:')) e.preventDefault();
  });

  wc.setWindowOpenHandler(({ url }) => {
    const provider = policy.isAppUrl(wc.getURL(), START_URL)
      && extLogin.loginProvider(url, (u) => policy.isAppUrl(u, START_URL));
    if (provider) {
      startExternalLogin(provider, url);
    } else if (policy.isDownloadUrl(url, START_URL) && policy.isAppUrl(wc.getURL(), START_URL)) {
      trace('window-open-download', { url: url.split('?')[0] });
      wc.downloadURL(url);
    } else if (policy.isSafeExternal(url)) {
      trace('window-open-external', { url });
      shell.openExternal(url);
    }
    return { action: 'deny' };
  });
}

const OFFLINE_POLL_MS = 5000;
let offlinePoll = null;

function stopOfflinePoll() {
  if (offlinePoll) { clearInterval(offlinePoll); offlinePoll = null; }
}

function showOffline(target, desc) {
  if (!win) return;
  trace('offline-page', { desc });
  localKind = 'offline';
  win.loadURL(localPage.load('offline.html', { u: target, d: desc }));
  stopOfflinePoll();
  let busy = false;
  offlinePoll = setInterval(async () => {
    if (busy || !win || localKind !== 'offline') return;
    busy = true;
    try {
      await session.fromPartition(PARTITION).fetch(target, { method: 'HEAD', cache: 'no-store' });
      trace('offline-recovered', {});
      stopOfflinePoll();
      win && win.loadURL(target);
    } catch (_) { } finally { busy = false; }
  }, OFFLINE_POLL_MS);
}

function bringToFront() {
  if (!win) { createWindow(); return; }
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
  if (process.platform === 'darwin') app.focus({ steal: true });
}

function startExternalLogin(provider, originalUrl) {
  if (!win) return;
  const { challenge } = pendingLogin.begin(provider);
  const ext = extLogin.externalStartUrl(START_URL, provider, challenge, originalUrl);
  trace('external-login-start', { provider });
  shell.openExternal(ext);
  const again = new URL('/auth/' + provider, START_URL).toString();
  localKind = 'wait';
  win.loadURL(localPage.load('login-wait.html', { p: provider, u: START_URL, r: again }));
}

let protocolQueue = Promise.resolve();
function onProtocolUrl(url) {
  protocolQueue = protocolQueue.then(() => handleProtocolUrl(url)).catch(() => {});
}

async function handleProtocolUrl(url) {
  const cb = extLogin.parseCallback(url);
  if (!cb) { trace('protocol-ignored', {}); return; }
  if (pendingLogin.seen(cb.code)) { trace('external-login-duplicate', {}); return; }
  if (!app.isReady()) await app.whenReady();
  const p = pendingLogin.peek();
  if (!p) { trace('external-login-no-pending', {}); bringToFront(); return; }
  bringToFront();
  try {
    const linking = linkPending;
    await exchangeLogin(cb.code, p.verifier, linking ? CLOUD_URL : START_URL);
    pendingLogin.finish();
    linkPending = false;
    trace('external-login-done', { provider: p.provider, link: linking });
    if (linking) {
      if (win) win.webContents.send('desktop:cloud-linked');
      notify('已連結 iamdirector 帳號', '現在可以把作品上傳到雲端資產庫了');
    } else {
      win && win.loadURL(START_URL);
    }
  } catch (err) {
    trace('external-login-failed', { provider: p.provider, status: err.status || 0 });
    if (!win) return;
    const message = { 429: '登入太頻繁，請稍後再試。', 503: '登入服務暫時無法使用，請稍後再試。' }[err.status]
      || '登入沒有完成，請再試一次。';
    dialog.showMessageBox(win, { type: 'warning', title: '登入沒有完成', message });
  }
}

const EXCHANGE_PATH = '/api/auth/desktop-exchange';
async function exchangeLogin(code, verifier, base) {
  const ses = session.fromPartition(PARTITION);
  const res = await ses.fetch(new URL(EXCHANGE_PATH, base || START_URL).toString(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, verifier }),
    credentials: 'include',
    redirect: 'error',
  });
  const body = await res.json().catch(() => null);
  if (!res.ok || !body || body.ok !== true) { const e = new Error('exchange failed'); e.status = res.status; throw e; }
}

app.on('web-contents-created', (_e, wc) => {
  wc.on('will-attach-webview', (e) => e.preventDefault());
});

function setupSession() {
  const ses = session.fromPartition(PARTITION);

  const ALLOWED = new Set(['notifications', 'fullscreen', 'clipboard-sanitized-write']);
  ses.setPermissionRequestHandler((wc, perm, cb, details) => {
    cb(ALLOWED.has(perm) && policy.isAppUrl(details.requestingUrl || wc.getURL(), START_URL));
  });
  ses.setPermissionCheckHandler((wc, perm, origin) =>
    ALLOWED.has(perm) && policy.isAppUrl(origin || '', START_URL));

  ses.webRequest.onHeadersReceived({ urls: ['http://*/*', 'https://*/*'] }, (d, cb) => {
    const h = d.responseHeaders || {};
    if (d.resourceType === 'mainFrame' && policy.isAppUrl(d.url, START_URL)
        && !Object.keys(h).some((k) => k.toLowerCase() === 'content-security-policy')) {
      h['Content-Security-Policy'] = [policy.BASELINE_CSP];
    }
    cb({ responseHeaders: h });
  });

  ses.on('will-download', onDownload);
  if (localSrv) {
    const port = new URL(START_URL).port;
    ses.webRequest.onBeforeSendHeaders({ urls: ['http://127.0.0.1:' + port + '/*'] }, (d, cb) => {
      const h = d.requestHeaders || {};
      if (localServer.needsToken(d.url, Number(port))) h[localServer.TOKEN_HEADER] = localSrv.token;
      cb({ requestHeaders: h });
    });
  }
}

function onDownload(_e, item, wc) {
  const s = settings.get();
  const name = policy.downloadFilename(item.getFilename(), item.getURL(), item.getMimeType());
  const dir = s.downloadDir && fs.existsSync(s.downloadDir) ? s.downloadDir : null;
  const quiet = dir && !s.askEveryDownload && wc && policy.isAppUrl(wc.getURL(), START_URL)
    && policy.isQuietDownload(name);
  trace('download-start', { name, quiet: !!quiet });
  if (quiet) {
    item.setSavePath(uniquePath(path.join(dir, name)));
  } else {
    item.setSaveDialogOptions({
      title: '儲存成片',
      defaultPath: path.join(dir || app.getPath('downloads'), name),
    });
  }
  item.once('done', (_ev, state) => {
    trace('download-done', { state, path: item.getSavePath() });
    if (state !== 'completed') return;
    const saved = item.getSavePath();
    if (!s.askEveryDownload || !s.downloadDir) settings.set({ downloadDir: path.dirname(saved) });
    notify('下載完成', path.basename(saved), () => shell.showItemInFolder(saved));
  });
}

function uniquePath(p) {
  if (!fs.existsSync(p)) return p;
  const { dir, name, ext } = path.parse(p);
  for (let i = 2; i < 1000; i++) {
    const c = path.join(dir, `${name} (${i})${ext}`);
    if (!fs.existsSync(c)) return c;
  }
  return p;
}

async function chooseDownloadDir() {
  const r = await dialog.showOpenDialog(win, {
    title: '成片要存到哪個資料夾',
    defaultPath: settings.get().downloadDir || app.getPath('downloads'),
    properties: ['openDirectory', 'createDirectory'],
  });
  if (!r.canceled && r.filePaths[0]) settings.set({ downloadDir: r.filePaths[0] });
  buildMenu();
}

function attention() {
  if (!win || win.isFocused()) return;
  if (process.platform === 'darwin' && app.dock) app.dock.bounce('informational');
  else win.flashFrame(true);
}

function notify(title, body, onClick) {
  if (!Notification.isSupported()) { attention(); return; }
  const n = new Notification({ title, body: String(body || '').slice(0, 200), silent: false });
  n.on('show', () => trace('notification-shown', { title, body }));
  n.on('failed', (_e, err) => { trace('notification-failed', { title, err: String(err) }); attention(); });
  n.on('click', () => {
    if (win) { if (win.isMinimized()) win.restore(); win.focus(); }
    if (onClick) onClick();
  });
  n.show();
}

ipcMain.on('desktop:reveal', (e, p) => {
  if (!win || e.sender !== win.webContents || MODE !== 'local') return;
  if (!policy.isAppUrl(e.senderFrame?.url || '', START_URL)) return;
  const root = path.join(app.getPath('userData'), 'local', 'exports') + path.sep;
  const full = path.resolve(String(p || ''));
  if (!full.startsWith(root) || !/\.(mp4|webm|srt)$/i.test(full) || !fs.existsSync(full)) {
    trace('reveal-refused', {});
    return;
  }
  shell.showItemInFolder(full);
});

const CLOUD_URL = localServer.gatewayOverride(process.env.IAMDIRECTOR_CLOUD_URL, app.isPackaged) || policy.PROD_URL;
let linkPending = false;

function fromOwnPage(e) {
  return !!win && e.sender === win.webContents && policy.isAppUrl(e.senderFrame?.url || '', START_URL);
}

function cloudFetch(p, opts = {}) {
  return session.fromPartition(PARTITION).fetch(new URL(p, CLOUD_URL).toString(),
    { credentials: 'include', redirect: 'error', cache: 'no-store', ...opts });
}

function localFetch(p, opts = {}) {
  const headers = { ...(opts.headers || {}), [localServer.TOKEN_HEADER]: localSrv.token };
  return fetch(new URL(p, START_URL).toString(), { ...opts, headers, redirect: 'error' });
}

async function okJson(res, what) {
  const d = await res.json().catch(() => ({}));
  if (!res.ok) { const e = new Error((d && d.error) || (what + '失敗（' + res.status + '）')); e.status = res.status; e.body = d; throw e; }
  return d;
}

const wait = (ms) => new Promise((ok) => setTimeout(ok, ms));
const cloudClient = {
  works: async () => (await okJson(await cloudFetch('/api/cloud/works'), '讀雲端作品')).works || [],
  check: async (shas) => (await okJson(await cloudFetch('/api/cloud/media/check', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ shas }) }), '比對雲端媒體')).missing || [],
  upload: async (sha, mime, reader) => {
    const CHUNK = 8 * 1024 * 1024;
    let offset = 0; let busy = 0; let resumes = 0;
    for (;;) {
      const len = Math.min(CHUNK, reader.size - offset);
      const body = len > 0 ? await reader.read(offset, len) : Buffer.alloc(0);
      const res = await cloudFetch('/api/cloud/media/chunk?sha=' + sha + '&mime=' + encodeURIComponent(mime)
        + '&size=' + reader.size + '&offset=' + offset,
      { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body });
      const d = await res.json().catch(() => ({}));
      if (res.status === 429 && busy++ < 6) { await wait(5000); offset = Number.isInteger(d.received) ? d.received : offset; continue; }
      if (res.status === 409 && Number.isInteger(d.received) && resumes++ < 3) { offset = d.received; continue; }
      if (!res.ok) { const e = new Error(d.error || ('上傳媒體失敗（' + res.status + '）')); e.status = res.status; throw e; }
      if (d.done) return d;
      offset = d.received;
    }
  },
  put: async (body) => {
    const res = await cloudFetch('/api/cloud/works/put', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (res.status === 409) { const d = await res.json().catch(() => ({})); if (d.conflict) return d; }
    return okJson(res, '上傳作品');
  },
  get: async (id) => okJson(await cloudFetch('/api/cloud/works/get?local_id=' + encodeURIComponent(id)), '讀雲端作品'),
  media: async (sha) => {
    const res = await cloudFetch('/api/cloud/media?sha=' + sha);
    if (!res.ok) throw new Error('雲端媒體取不回來（' + res.status + '）');
    return res;
  },
};

const localClient = {
  bundle: async (pid) => okJson(await localFetch('/api/local/work-bundle?project_id=' + encodeURIComponent(pid)), '整理作品'),
  getState: async () => (await okJson(await localFetch('/api/store?key=cloud_sync'), '讀同步狀態')).value || {},
  saveState: async (v) => okJson(await localFetch('/api/store?key=cloud_sync', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value: v }) }), '存同步狀態'),
  mediaReader: async (sha) => {
    if (!/^[0-9a-f]{64}$/.test(sha)) throw new Error('sha 不合法');
    const file = path.join(app.getPath('userData'), 'local', 'media', sha);
    const size = fs.statSync(file).size;
    return {
      size,
      read: async (off, len) => {
        const fd = fs.openSync(file, 'r');
        try { const buf = Buffer.alloc(len); fs.readSync(fd, buf, 0, len, off); return buf; } finally { fs.closeSync(fd); }
      },
    };
  },
  hasMedia: async (sha) => (await localFetch('/api/local/media?sha=' + sha, { method: 'HEAD' })).ok,
  putMedia: async (sha, mime, data) => {
    const streaming = data && typeof data.arrayBuffer === 'function' && data.body;
    const len = streaming ? data.headers.get('content-length') : null;
    const opts = { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: streaming ? data.body : data };
    if (streaming) { opts.duplex = 'half'; if (len) opts.headers['Content-Length'] = len; }
    return okJson(await localFetch('/api/local/media?sha=' + sha + '&mime=' + encodeURIComponent(mime), opts), '存媒體');
  },
  importWork: async (manifest, asNew) => okJson(await localFetch('/api/local/work-import', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ manifest, as_new: asNew }) }), '寫回作品'),
};

async function askConflict({ name, cloudRev, cloudUpdatedAt }) {
  const r = await dialog.showMessageBox(win, {
    type: 'question', buttons: ['留本機版', '留雲端版', '兩份都留', '取消'], defaultId: 3, cancelId: 3,
    title: '兩邊都改過了',
    message: `「${name}」在這台電腦和雲端都改過了，要留哪一份？`,
    detail: `雲端是第 ${cloudRev} 版${cloudUpdatedAt ? '（' + String(cloudUpdatedAt).slice(0, 16).replace('T', ' ') + '）' : ''}。\n`
      + '留本機版：用這台電腦的覆蓋雲端。\n留雲端版：用雲端的覆蓋這台電腦的。\n兩份都留：雲端那份另存成一部新作品，這一部不動。',
  });
  return ['local', 'cloud', 'both', null][r.response];
}

ipcMain.handle('desktop:cloud-status', async (e) => {
  if (!fromOwnPage(e) || MODE !== 'local') return { linked: false };
  try {
    const res = await cloudFetch('/api/cloud/works');
    return { linked: res.status === 200, unavailable: res.status === 503, status: res.status, host: new URL(CLOUD_URL).host };
  } catch (_) { return { linked: false, offline: true, host: new URL(CLOUD_URL).host }; }
});

ipcMain.handle('desktop:cloud-link', async (e, provider) => {
  if (!fromOwnPage(e) || MODE !== 'local') return { ok: false };
  if (!extLogin.PROVIDERS.includes(provider)) return { ok: false, error: '不支援這個登入方式' };
  const { challenge } = pendingLogin.begin(provider);
  linkPending = true;
  trace('cloud-link-start', { provider });
  shell.openExternal(extLogin.externalStartUrl(CLOUD_URL, provider, challenge, CLOUD_URL));
  return { ok: true };
});

async function localIds() {
  const d = await okJson(await localFetch('/api/projects'), '讀本機作品');
  return new Set((d.projects || []).map((p) => String(p.id).replace(/-/g, '')));
}
ipcMain.handle('desktop:cloud-list', async (e) => {
  if (!fromOwnPage(e) || MODE !== 'local' || !localSrv) return { error: '只有本機模式能用' };
  try {
    const [works, have] = await Promise.all([cloudClient.works(), localIds()]);
    return { works: works.map((w) => ({ local_id: w.local_id, name: w.name, rev: w.rev, updated_at: w.updated_at,
      here: have.has(w.local_id) })) };
  } catch (err) {
    return err.status === 401 ? { needLogin: true } : { error: String(err.message || err).slice(0, 200) };
  }
});
ipcMain.handle('desktop:cloud-pull', async (e, localId) => {
  if (!fromOwnPage(e) || MODE !== 'local' || !localSrv) return { result: 'error', error: '只有本機模式能用' };
  if (!/^[A-Za-z0-9_-]{8,64}$/.test(String(localId || ''))) return { result: 'error', error: '作品 id 不合法' };
  if (syncing) return { result: 'busy' };
  syncing = true;
  try {
    return await cloudSync.pullNew({ localId, local: localClient, cloud: cloudClient, existing: await localIds() });
  } catch (err) {
    if (err.status === 401) return { result: 'need-login' };
    return { result: 'error', error: String(err.message || err).slice(0, 200) };
  } finally { syncing = false; }
});

let syncing = false;
ipcMain.handle('desktop:cloud-sync', async (e, pid) => {
  if (!fromOwnPage(e) || MODE !== 'local' || !localSrv) return { result: 'error', error: '只有本機模式能同步' };
  if (!/^[0-9a-fA-F-]{36}$/.test(String(pid || ''))) return { result: 'error', error: '作品 id 不合法' };
  if (syncing) return { result: 'busy' };
  syncing = true;
  try {
    const r = await cloudSync.syncWork({ pid, local: localClient, cloud: cloudClient, ask: askConflict });
    trace('cloud-sync', { result: r.result });
    return r;
  } catch (err) {
    trace('cloud-sync-failed', { status: err.status || 0 });
    if (err.status === 401) return { result: 'need-login' };
    return { result: 'error', error: String(err.message || err).slice(0, 200) };
  } finally { syncing = false; }
});

let liveJobs = 0;
ipcMain.on('desktop:live-jobs', (e, n) => {
  e.returnValue = true;
  if (!win || e.sender !== win.webContents) return;
  liveJobs = Number.isInteger(n) && n >= 0 ? n : 0;
});

ipcMain.on('desktop:notify', (e, msg) => {
  if (!win || e.sender !== win.webContents) return;
  if (!policy.isAppUrl(e.senderFrame?.url || '', START_URL)) return;
  const kinds = { job: '生成完成', export: '匯出完成' };
  if (!msg || !kinds[msg.kind]) return;
  trace('notify-request', { kind: msg.kind, focused: win.isFocused() });
  if (win.isFocused()) return;
  notify(kinds[msg.kind], typeof msg.text === 'string' ? msg.text : '');
});

let localRuntime = null;
let h264Busy = null;

function bunzip2(buf) {
  return new Promise((ok, bad) => {
    const child = spawn(localRuntime.python, ['-I', '-c',
      'import bz2,sys; sys.stdout.buffer.write(bz2.decompress(sys.stdin.buffer.read()))'],
    { stdio: ['pipe', 'pipe', 'ignore'], windowsHide: true });
    const out = [];
    let n = 0;
    child.stdout.on('data', (c) => { n += c.length; if (n > openh264.MAX_BYTES) child.kill(); else out.push(c); });
    child.on('error', bad);
    child.on('exit', (code) => (code === 0 ? ok(Buffer.concat(out)) : bad(new Error('解壓失敗'))));
    child.stdin.on('error', () => {});
    child.stdin.end(buf);
  });
}

async function downloadCisco(url) {
  const res = await net.fetch(url, { redirect: 'error', cache: 'no-store' });
  if (!res.ok) throw new Error('Cisco 伺服器回 ' + res.status);
  const len = Number(res.headers.get('content-length') || 0);
  if (len > openh264.MAX_BYTES) throw new Error('下載的檔案大小不對');
  const buf = Buffer.from(await res.arrayBuffer());
  return buf;
}

async function installOpenH264() {
  const dir = await openh264.install({ fs, userData: app.getPath('userData'), download: downloadCisco, bunzip2 });
  settings.set({ openh264: 'enabled' });
  if (!localSrv || !(await localSrv.setOpenH264(dir))) throw new Error('本機服務沒有接受這個編碼器，請重新開啟 App 再試');
  trace('openh264-installed', {});
  return dir;
}

async function ensureH264() {
  const ud = app.getPath('userData');
  const pref = settings.get().openh264;
  if (pref === 'enabled') {
    const d = openh264.verifyInstalled({ fs, userData: ud });
    if (d && localSrv && await localSrv.setOpenH264(d)) return 'ready';
  }
  if (pref === 'disabled') return 'declined';
  const r = await dialog.showMessageBox(win, {
    type: 'question', title: openh264.ASK.title, message: openh264.ASK.message, detail: openh264.ASK.detail,
    buttons: openh264.ASK.buttons, defaultId: 0, cancelId: 1, checkboxLabel: openh264.ASK.remember,
  });
  if (r.response !== 0) {
    if (r.checkboxChecked) settings.set({ openh264: 'disabled' });
    trace('openh264-declined', { remember: !!r.checkboxChecked });
    return 'declined';
  }
  try { await installOpenH264(); return 'ready'; } catch (err) {
    trace('openh264-failed', { error: String(err.message || err).slice(0, 120) });
    await dialog.showMessageBox(win, { type: 'warning', title: openh264.ASK.title,
      message: 'H.264 編碼器沒有裝好，這次改匯出 WebM', detail: String(err.message || err).slice(0, 200) });
    return 'failed';
  }
}

ipcMain.handle('desktop:h264-ensure', async (e) => {
  if (!fromOwnPage(e) || MODE !== 'local' || !localRuntime
      || !openh264.applies({ fs, platform: process.platform, ffmpegDir: localRuntime.ffmpegDir })) return 'unavailable';
  if (!h264Busy) h264Busy = ensureH264().finally(() => { h264Busy = null; });
  return h264Busy;
});

async function openh264Settings() {
  const ud = app.getPath('userData');
  const on = settings.get().openh264 === 'enabled' && !!openh264.verifyInstalled({ fs, userData: ud });
  const r = await dialog.showMessageBox(win, {
    type: 'info', title: openh264.ASK.title,
    message: on ? 'H.264 編碼器已啟用：匯出 MP4' : 'H.264 編碼器未啟用：匯出時會先問你，或改匯出 WebM',
    detail: openh264.NOTICE + '\n\n版本 ' + openh264.VERSION + '，由這台電腦直接從 ciscobinary.openh264.org 下載。'
      + '授權條款見「關於／第三方授權」（THIRD_PARTY_NOTICES）。',
    buttons: on ? ['停用', '關閉'] : ['啟用（從 Cisco 下載）', '關閉'], defaultId: 1, cancelId: 1,
  });
  if (r.response !== 0) return;
  if (on) {
    settings.set({ openh264: 'disabled' });
    openh264.remove({ fs, userData: ud });
    if (localSrv) localSrv.setOpenH264(null);
    trace('openh264-disabled', {});
    return;
  }
  try { await installOpenH264(); } catch (err) {
    await dialog.showMessageBox(win, { type: 'warning', title: openh264.ASK.title,
      message: 'H.264 編碼器沒有裝好', detail: String(err.message || err).slice(0, 200) });
  }
}

function buildMenu() {
  const s = settings.get();
  const go = (p) => () => win && win.loadURL(new URL(p, START_URL).toString());
  const template = menu.buildTemplate({
    isMac: process.platform === 'darwin',
    dev: DEV,
    version: app.getVersion(),
    askEveryDownload: s.askEveryDownload,
    downloadDir: s.downloadDir,
    updateConfigured: updater.configured(),
    mode: MODE,
    autoInstallOnQuit: s.autoInstallOnQuit !== false,
    actions: {
      goHome: go('/'),
      chooseDownloadDir,
      toggleAskEveryDownload: (mi) => settings.set({ askEveryDownload: mi.checked }),
      openDownloadDir: () => s.downloadDir && shell.openPath(s.downloadDir),
      goBack: () => win?.webContents.navigationHistory.goBack(),
      goForward: () => win?.webContents.navigationHistory.goForward(),
      openInBrowser: () => win && policy.isSafeExternal(win.webContents.getURL()) && shell.openExternal(win.webContents.getURL()),
      checkUpdatesNow: () => updater.checkNow(settings.get),
      toggleAutoInstallOnQuit: (mi) => { settings.set({ autoInstallOnQuit: mi.checked }); updater.setAutoInstallOnQuit(mi.checked); },
      showUpdateInfo,
      switchMode,
      openh264Settings: localRuntime && openh264.applies({ fs, platform: process.platform, ffmpegDir: localRuntime.ffmpegDir })
        ? openh264Settings : null,
    },
  });
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function showUpdateInfo() {
  const t = menu.updateUnavailableText(app.getVersion());
  const r = await dialog.showMessageBox(win, {
    type: 'info', title: '檢查更新', message: t.message, detail: t.detail,
    buttons: ['前往官網', '好'], defaultId: 0, cancelId: 1,
  });
  trace('update-info', { response: r.response });
  if (r.response === 0) shell.openExternal(menu.DOWNLOAD_PAGE);
}

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

async function decideMode() {
  let hasCloudSession = false;
  try {
    const got = await session.fromPartition(PARTITION).cookies.get({ url: policy.PROD_URL, name: 'studio_session' });
    hasCloudSession = got.length > 0;
  } catch (_) {}
  return modeMod.decide({ saved: settings.get().mode, envUrl: process.env.IAMDIRECTOR_URL, hasCloudSession });
}

async function startLocal() {
  const keystore = keystoreMod.create({ safeStorage, fs, userData: app.getPath('userData'), platform: process.platform });
  const runtime = localServer.resolveRuntime({
    isPackaged: app.isPackaged, resourcesPath: process.resourcesPath, env: process.env, platform: process.platform,
  });
  localRuntime = runtime;
  const oh = openh264.applies({ fs, platform: process.platform, ffmpegDir: runtime.ffmpegDir })
    && settings.get().openh264 === 'enabled' ? openh264.verifyInstalled({ fs, userData: app.getPath('userData') }) : null;
  const srv = localServer.start({
    spawn, runtime, keystore, openh264Dir: oh,
    dataDir: path.join(app.getPath('userData'), 'local'),
    gatewayBase: localServer.gatewayOverride(process.env.IAMDIRECTOR_GATEWAY_BASE, app.isPackaged),
    onExit: (code) => {
      trace('local-server-exit', { code });
      if (localSrv === srv && !quitting && win) {
        dialog.showMessageBox(win, { type: 'error', title: '本機服務停止了',
          message: '本機服務意外停止，請重新開啟「我是導演」。作品都還在這台電腦上。' });
      }
    },
  });
  const port = await srv.ready;
  localSrv = srv;
  START_URL = 'http://127.0.0.1:' + port + '/';
  policy.setLocalOnly(true);
  trace('local-server-ready', { pid: srv.pid });
}

async function switchMode() {
  const to = MODE === 'local' ? 'cloud' : 'local';
  const r = await dialog.showMessageBox(win, {
    type: 'question', buttons: ['切換並重新開啟', '取消'], defaultId: 0, cancelId: 1,
    title: to === 'cloud' ? '登入 iamdirector 帳號' : '改用本機模式',
    message: to === 'cloud'
      ? '切換到雲端版並登入。本機的作品會留在這台電腦，隨時可以切回來。'
      : '切換到本機模式（不用登入）。雲端的作品不會受影響。',
  });
  if (r.response !== 0) return;
  settings.set({ mode: to });
  quitting = true;
  if (localSrv) localSrv.stop();
  app.relaunch();
  app.exit(0);
}

let quitting = false;
app.on('will-quit', () => { quitting = true; if (localSrv) localSrv.stop(); });

ipcMain.on('desktop:switch-mode', (e) => {
  if (!win || e.sender !== win.webContents) return;
  if (!policy.isAppUrl(e.senderFrame?.url || '', START_URL)) return;
  switchMode();
});

app.whenReady().then(async () => {
  settings.init(app.getPath('userData'));
  MODE = await decideMode();
  if (MODE === 'local') {
    try {
      await startLocal();
    } catch (err) {
      trace('local-server-failed', { message: String(err && err.message) });
      const r = await dialog.showMessageBox({ type: 'error', buttons: ['改用雲端版（登入）', '結束'], defaultId: 0, cancelId: 1,
        title: '本機服務沒有啟動', message: '本機服務沒有啟動，暫時不能用本機模式。', detail: String(err && err.message) });
      if (r.response !== 0) { app.exit(1); return; }
      MODE = 'cloud';
      settings.set({ mode: 'cloud' });
    }
  }
  setupSession();
  buildMenu();
  createWindow();
  updater.start(settings.get);
  app.on('activate', () => { if (!win) createWindow(); });
  const link = extLogin.findProtocolArg(process.argv);
  if (link) onProtocolUrl(link);
});

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
