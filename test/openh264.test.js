'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const oh = require('../src/openh264');

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'oh264-'));

test('雜湊與本機伺服器（studio_local.py）寫死的那一份相同', () => {
  const py = fs.readFileSync(path.join(__dirname, '..', 'local-server', 'local', 'studio_local.py'), 'utf8');
  const m = py.match(/^OPENH264_SHA256 = ["']([0-9a-f]{64})["']/m);
  assert.ok(m, 'studio_local.py 要有 OPENH264_SHA256');
  assert.strictEqual(m[1], oh.SO_SHA256);
  assert.match(py, new RegExp('^OPENH264_SO = ["\']' + oh.SO_NAME.replace(/\./g, '\\.') + '["\']', 'm'));
});

test('只從 Cisco 的 https 下載、版本對得上', () => {
  assert.strictEqual(new URL(oh.URL).origin, 'https://ciscobinary.openh264.org');
  assert.ok(oh.URL.includes('-' + oh.VERSION + '-'));
});

test('只在 Linux、ffmpeg 旁邊有空殼時需要', () => {
  const d = tmp();
  assert.strictEqual(oh.applies({ fs, platform: 'linux', ffmpegDir: d }), false);
  fs.writeFileSync(path.join(d, oh.SO_NAME), 'stub');
  assert.strictEqual(oh.applies({ fs, platform: 'linux', ffmpegDir: d }), true);
  assert.strictEqual(oh.applies({ fs, platform: 'darwin', ffmpegDir: d }), false);
  assert.strictEqual(oh.applies({ fs, platform: 'linux', ffmpegDir: null }), false);
});

test('下載的檔案雜湊不對：拒用、不留任何檔案、不解壓', async () => {
  const ud = tmp();
  let unzipped = false;
  await assert.rejects(oh.install({ fs, userData: ud, download: async () => Buffer.from('fake bz2'),
    bunzip2: async () => { unzipped = true; return Buffer.from('x'); } }), /比對不符/);
  assert.strictEqual(unzipped, false);
  assert.strictEqual(fs.existsSync(oh.dirOf(ud)), false);
});

test('超過大小上限：拒用', async () => {
  const ud = tmp();
  await assert.rejects(oh.install({ fs, userData: ud, download: async () => Buffer.alloc(oh.MAX_BYTES + 1),
    bunzip2: async () => Buffer.from('x') }), /大小/);
});

test('已安裝的檔案被換掉：verifyInstalled 拒用並刪掉', () => {
  const ud = tmp();
  fs.mkdirSync(oh.dirOf(ud), { recursive: true });
  const f = path.join(oh.dirOf(ud), oh.SO_NAME);
  fs.writeFileSync(f, 'not cisco');
  assert.strictEqual(oh.verifyInstalled({ fs, userData: ud }), null);
  assert.strictEqual(fs.existsSync(f), false);
  assert.strictEqual(oh.verifyInstalled({ fs, userData: tmp() }), null, '沒裝過');
});

test('詢問文字：說明是向 Cisco 下載、附 Cisco 要求的那一句、拒絕就改 WebM', () => {
  assert.strictEqual(oh.NOTICE, 'OpenH264 Video Codec provided by Cisco Systems, Inc.');
  assert.match(oh.ASK.message, /Cisco/);
  assert.ok(oh.ASK.detail.includes(oh.NOTICE));
  assert.match(oh.ASK.detail, /WebM/);
  assert.match(oh.ASK.detail, /停用/, '告訴使用者在哪裡可以停用（授權條件 2）');
});

test('Cisco 的授權全文附在 repo、THIRD_PARTY_NOTICES 有寫', () => {
  const lic = fs.readFileSync(path.join(__dirname, '..', 'licenses', 'OpenH264-BINARY_LICENSE.txt'), 'utf8');
  assert.match(lic, /AVC\/H\.264 Patent Portfolio License Conditions/);
  const tp = fs.readFileSync(path.join(__dirname, '..', 'THIRD_PARTY_NOTICES.md'), 'utf8');
  assert.ok(tp.includes(oh.NOTICE));
  assert.match(tp, /THIS PRODUCT IS LICENSED UNDER THE AVC PATENT PORTFOLIO LICENSE/);
});
