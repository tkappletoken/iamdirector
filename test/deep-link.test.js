'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const d = require('../src/deep-link');
const x = require('../src/external-login');

const ID16 = 'apv_' + 'A1b2C3d4E5f6G7h8';
const ID32 = 'apv_' + 'z'.repeat(32);

test('核准連結：iamdirector://approve/<apv_ id> 取得 id', () => {
  assert.deepEqual(d.parseApprove('iamdirector://approve/' + ID16), { id: ID16 });
  assert.deepEqual(d.parseApprove('iamdirector://approve/' + ID32), { id: ID32 });
});

const APB16 = 'apb_' + 'Q1w2E3r4T5y6U7i8';
const APB32 = 'apb_' + '9'.repeat(32);

test('批次卡連結：iamdirector://approve/<apb_ id> 也認（16–32 位英數，可帶一個結尾斜線）', () => {
  assert.deepEqual(d.parseApprove('iamdirector://approve/' + APB16), { id: APB16 });
  assert.deepEqual(d.parseApprove('iamdirector://approve/' + APB32), { id: APB32 });
  assert.deepEqual(d.parseApprove('iamdirector://approve/' + APB16 + '/'), { id: APB16 });
});

test('批次卡連結：格式不對一律不認', () => {
  for (const u of [
    'iamdirector://approve/apb_' + 'a'.repeat(15),
    'iamdirector://approve/apb_' + 'a'.repeat(33),
    'iamdirector://approve/APB_' + 'a'.repeat(16),
    'iamdirector://approve/apb-' + 'a'.repeat(16),
    'iamdirector://approve/apc_' + 'a'.repeat(16),
    'iamdirector://approve/ap_' + 'a'.repeat(16),
    'iamdirector://approve/apbv_' + 'a'.repeat(16),
    'iamdirector://approve/apb_' + 'a'.repeat(15) + '_',
    'iamdirector://approve/' + APB16 + '//',
    'iamdirector://approve/' + APB16 + '?x=1',
    'iamdirector://approve/' + APB16 + '#x',
    'iamdirector://approve/../' + APB16,
    'iamdirector://approve/%61pb_' + 'a'.repeat(16),
    'iamdirector://approve:1/' + APB16,
    'iamdirector://u@approve/' + APB16,
    'iamdirector://auth/' + APB16,
  ]) assert.equal(d.parseApprove(u), null, u);
});

test('核准連結：剛好一個結尾斜線也認（有些 Windows 瀏覽器會補），兩個以上不認', () => {
  assert.deepEqual(d.parseApprove('iamdirector://approve/' + ID16 + '/'), { id: ID16 });
  assert.deepEqual(d.parseApprove('iamdirector://approve/' + ID32 + '/'), { id: ID32 });
  for (const u of [
    'iamdirector://approve/' + ID16 + '//',
    'iamdirector://approve/' + ID16 + '///',
    'iamdirector://approve/' + ID16 + '/?x=1',
    'iamdirector://approve/' + ID16 + '/#x',
    'iamdirector://approve/' + ID16 + '/ ',
    'iamdirector://approve//' + ID16,
    'iamdirector://approve//' + ID16 + '/',
    'iamdirector://approve/apv_' + 'a'.repeat(15) + '/',
    'iamdirector://approve/' + ID16 + '/.',
    'iamdirector://approve/' + ID16 + '/..',
  ]) assert.equal(d.parseApprove(u), null, u);
});

test('核准連結：格式不對一律不認', () => {
  for (const u of [
    'iamdirector://approve/apv_' + 'a'.repeat(15),
    'iamdirector://approve/apv_' + 'a'.repeat(33),
    'iamdirector://approve/APV_' + 'a'.repeat(16),
    'iamdirector://approve/apv-' + 'a'.repeat(16),
    'iamdirector://approve/apv_' + 'a'.repeat(15) + '_',
    'iamdirector://approve/' + ID16 + '/x',
    'iamdirector://approve/x/' + ID16,
    'iamdirector://approve/../' + ID16,
    'iamdirector://approve/./' + ID16,
    'iamdirector://approve/%61pv_' + 'a'.repeat(16),
    'iamdirector://approve/' + ID16 + '?next=/x',
    'iamdirector://approve/' + ID16 + '#x',
    'iamdirector://approve/' + ID16 + '%20',
    'iamdirector://approve:8080/' + ID16,
    'iamdirector://user@approve/' + ID16,
    'iamdirector://user:pw@approve/' + ID16,
    'iamdirector://approvex/' + ID16,
    'IAMDIRECTOR://APPROVE/' + ID16,
    'iamdirector://APPROVE/' + ID16,
    'iamdirector://auth/' + ID16,
    'iamdirector:approve/' + ID16,
    'iamdirector:///approve/' + ID16,
    'https://approve/' + ID16,
    'iamdirector://approve/',
    'iamdirector://approve',
    '',
    null,
    undefined,
    42,
  ]) assert.equal(d.parseApprove(u), null, String(u));
});

test('核准連結和登入回呼互不搶：各自只認自己的', () => {
  const cb = 'iamdirector://auth/callback?code=' + 'A'.repeat(43);
  assert.equal(d.parseApprove(cb), null);
  assert.equal(x.parseCallback('iamdirector://approve/' + ID16), null);
  assert.equal(x.findProtocolArg(['/app/iamdirector', 'iamdirector://approve/' + ID16]), 'iamdirector://approve/' + ID16);
});

test('冷啟動：連結先存著，頁面載完拿一次就清掉', () => {
  const box = d.createInbox(() => 1000);
  assert.equal(box.take(), null);
  box.put(ID16);
  assert.equal(box.take(), ID16);
  assert.equal(box.take(), null);
});

test('冷啟動：連續來兩個只留最後一個', () => {
  const box = d.createInbox(() => 1000);
  box.put(ID16);
  box.put(ID32);
  assert.equal(box.take(), ID32);
  assert.equal(box.take(), null);
});

test('冷啟動：放太久的連結丟掉，不在之後的換頁突然打開', () => {
  let t = 0;
  const box = d.createInbox(() => t);
  box.put(ID16);
  t = d.INBOX_TTL_MS;
  assert.equal(box.take(), ID16);
  box.put(ID16);
  t += d.INBOX_TTL_MS + 1;
  assert.equal(box.take(), null);
});

// 假的 webContents：事件順序照 Electron 45.3.2 實測——did-finish-load 當下 isLoading() 還是 true，
// did-stop-loading 時才是 false（0.2.12 VM：冷啟動時連結先進暫存區，掛在 did-finish-load 上永遠送不出去）
function fakeWc(url) {
  const EventEmitter = require('node:events');
  const wc = new EventEmitter();
  let loading = false;
  wc.sent = [];
  wc.isDestroyed = () => false;
  wc.isLoading = () => loading;
  wc.getURL = () => url;
  wc.send = (ch, id) => wc.sent.push([ch, id]);
  wc.load = () => { loading = true; wc.emit('did-start-loading'); wc.emit('did-finish-load'); loading = false; wc.emit('did-stop-loading'); };
  wc.startLoading = () => { loading = true; };
  return wc;
}
const APP = 'http://127.0.0.1:5000/';
const isAppPage = (u) => u.startsWith(APP);

test('冷啟動：連結在頁面載入中到達，載完才送到頁面（只送一次）', () => {
  const box = d.createInbox(() => 1000);
  const dl = d.createDelivery({ inbox: box, isAppPage });
  const wc = fakeWc(APP);
  dl.attach(wc);
  wc.startLoading();
  box.put(ID16);
  assert.equal(dl.deliver(wc), false, '載入中不送');
  wc.load();
  assert.deepEqual(wc.sent, [['desktop:open-approval', ID16]]);
  wc.load();
  assert.equal(wc.sent.length, 1, '之後換頁不再送');
});

test('App 已開著：連結到了立刻送', () => {
  const box = d.createInbox(() => 1000);
  const dl = d.createDelivery({ inbox: box, isAppPage });
  const wc = fakeWc(APP);
  dl.attach(wc);
  box.put(ID32);
  assert.equal(dl.deliver(wc), true);
  assert.deepEqual(wc.sent, [['desktop:open-approval', ID32]]);
});

test('停在不是 App 的頁面（離線頁、登入等待頁）先不送，留到回 App 頁', () => {
  const box = d.createInbox(() => 1000);
  const dl = d.createDelivery({ inbox: box, isAppPage });
  const wc = fakeWc('data:text/html,offline');
  dl.attach(wc);
  box.put(ID16);
  wc.load();
  assert.equal(wc.sent.length, 0);
  wc.getURL = () => APP;
  wc.load();
  assert.deepEqual(wc.sent, [['desktop:open-approval', ID16]]);
});

test('通知：核准卡的 kind 有標題「有核准卡等你核准」', () => {
  const src = require('node:fs').readFileSync(require('node:path').join(__dirname, '..', 'src', 'main.js'), 'utf8');
  const m = src.match(/const kinds = (\{[^}]*\});/);
  assert.ok(m, 'main.js 找不到 desktop:notify 的 kinds');
  const kinds = Function('return ' + m[1])();
  assert.equal(kinds.approval, '有核准卡等你核准');
  assert.equal(kinds.job, '生成完成');
  assert.equal(kinds.export, '匯出完成');
});
