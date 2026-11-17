'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const m = require('../src/menu');

const noop = () => {};
const actions = new Proxy({}, { get: () => noop });
const base = { dev: true, version: '0.1.0', askEveryDownload: false, downloadDir: null, updateConfigured: false, actions };

function walk(items, out = []) {
  for (const it of items) {
    out.push(it);
    if (Array.isArray(it.submenu)) walk(it.submenu, out);
  }
  return out;
}

const AUTO_SUBMENU_ROLES = ['appMenu', 'fileMenu', 'editMenu', 'viewMenu', 'windowMenu', 'shareMenu'];
const CJK = /[一-鿿]/;

for (const isMac of [true, false]) {
  test(`選單（${isMac ? 'mac' : 'win'}）：每一項都有中文 label、沒有自動子選單 role`, () => {
    const all = walk(m.buildTemplate({ ...base, isMac }));
    for (const it of all) {
      if (it.type === 'separator') continue;
      assert.ok(typeof it.label === 'string' && CJK.test(it.label),
        `role=${it.role} 沒有中文 label：${JSON.stringify(it.label)}`);
      assert.ok(!AUTO_SUBMENU_ROLES.includes(it.role), `用了 ${it.role}，子項目會跟系統語言變英文`);
      if (it.role === 'help' || it.role === 'window') assert.ok(Array.isArray(it.submenu), `${it.role} 要自己給子選單`);
    }
  });
}

test('mac 的 App 選單：關於／隱藏／結束都在，而且是中文', () => {
  const app = m.buildTemplate({ ...base, isMac: true })[0];
  assert.equal(app.label, m.APP_NAME);
  const byRole = Object.fromEntries(app.submenu.filter((i) => i.role).map((i) => [i.role, i.label]));
  for (const r of ['about', 'services', 'hide', 'hideOthers', 'unhide', 'quit']) assert.ok(CJK.test(byRole[r] || ''), r);
});

function findUpdateItem(opts) {
  return walk(m.buildTemplate({ ...base, isMac: true, ...opts })).find((i) => i.label === '檢查更新…');
}

test('檢查更新：沒有發佈來源時仍可點，點了跳說明（不是灰的、也不是去連線）', () => {
  const calls = [];
  const acts = { ...Object.fromEntries(['checkUpdatesNow', 'showUpdateInfo'].map((k) => [k, () => calls.push(k)])) };
  const off = findUpdateItem({ updateConfigured: false, actions: new Proxy(acts, { get: (o, k) => o[k] || noop }) });
  assert.notEqual(off.enabled, false, '不能是灰的');
  off.click();
  const on = findUpdateItem({ updateConfigured: true, actions: new Proxy(acts, { get: (o, k) => o[k] || noop }) });
  assert.notEqual(on.enabled, false);
  on.click();
  assert.deepEqual(calls, ['showUpdateInfo', 'checkUpdatesNow']);
});

test('更新說明：寫出目前版本、不會自動更新、官網網址', () => {
  const t = m.updateUnavailableText('1.2.3');
  assert.match(t.detail, /目前版本 1\.2\.3/);
  assert.match(t.detail, /不會自動更新/);
  assert.ok(t.detail.includes('https://iamdirector.app'));
  assert.equal(m.DOWNLOAD_PAGE, 'https://iamdirector.app');
});

test('全螢幕：mac 交給系統（不自己放，免得出現兩次），Windows／Linux 自己放一個', () => {
  const fs = (isMac) => walk(m.buildTemplate({ ...base, isMac })).filter((i) => i.role === 'togglefullscreen');
  assert.equal(fs(true).length, 0);
  assert.equal(fs(false).length, 1);
});
