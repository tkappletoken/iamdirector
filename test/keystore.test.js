'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const ks = require('../src/keystore');

const FAKE = ['sk', 'test', 'x'.repeat(8), Date.now().toString(36)].join('-');

function fakeSafe({ available = true, backend = 'gnome_libsecret' } = {}) {
  return {
    isEncryptionAvailable: () => available,
    getSelectedStorageBackend: () => backend,
    encryptString: (s) => Buffer.from('ENC:' + Buffer.from(s).toString('base64')),
    decryptString: (b) => Buffer.from(String(b).slice(4), 'base64').toString(),
  };
}
function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'ks-')); }

test('存檔是密文、權限 0600，讀回來一樣；畫面只拿末四碼', () => {
  const dir = tmp();
  const k = ks.create({ safeStorage: fakeSafe(), fs, userData: dir, platform: 'darwin' });
  const r = k.save(FAKE);
  assert.deepEqual(r, { persisted: true, last4: FAKE.slice(-4) });
  const raw = fs.readFileSync(k.file);
  assert.ok(!raw.toString().includes(FAKE), '檔案裡不能有明文');
  if (process.platform !== 'win32') assert.equal(fs.statSync(k.file).mode & 0o777, 0o600);
  assert.equal(k.load(), FAKE);
  k.clear();
  assert.equal(k.load(), null);
  assert.ok(!fs.existsSync(k.file));
});

test('Linux basic_text（沒有 libsecret）：拒絕寫檔，只留這次執行的記憶體', () => {
  const dir = tmp();
  const k = ks.create({ safeStorage: fakeSafe({ backend: 'basic_text' }), fs, userData: dir, platform: 'linux' });
  const r = k.save(FAKE);
  assert.equal(r.persisted, false);
  assert.equal(r.reason, 'no_keyring');
  assert.ok(!fs.existsSync(k.file), '不准寫檔');
  assert.equal(k.load(), FAKE, '這次執行期間仍可用');
  const again = ks.create({ safeStorage: fakeSafe({ backend: 'basic_text' }), fs, userData: dir, platform: 'linux' });
  assert.equal(again.load(), null, '重開就沒有了');
});

test('加密不可用（任何平台）也拒存', () => {
  const dir = tmp();
  const k = ks.create({ safeStorage: fakeSafe({ available: false }), fs, userData: dir, platform: 'win32' });
  assert.equal(k.save(FAKE).persisted, false);
  assert.ok(!fs.existsSync(k.file));
});

test('格式不對的值不收（空白、控制字元、太短）', () => {
  const k = ks.create({ safeStorage: fakeSafe(), fs, userData: tmp(), platform: 'darwin' });
  for (const bad of ['', 'short', 'has space inside', 'line\nbreak', null]) {
    assert.throws(() => k.save(bad));
  }
});
