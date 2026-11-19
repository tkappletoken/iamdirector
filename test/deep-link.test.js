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
