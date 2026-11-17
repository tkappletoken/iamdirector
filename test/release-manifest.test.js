'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const V = '9.8.7';
const ELF = { x64: 62, arm64: 183 };

function fixture(skip = [], elfOverride = {}) {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'relman-'));
  const put = (n, head) => { const b = Buffer.alloc(4096); head.copy(b); fs.writeFileSync(path.join(d, n), b); };
  const elf = (arch) => { const b = Buffer.alloc(20); b.writeUInt32BE(0x7f454c46, 0); b.writeUInt16LE(ELF[arch], 18); return b; };
  const files = {
    [`iamdirector-${V}-mac-arm64.dmg`]: Buffer.from('dmg'), [`iamdirector-${V}-mac-x64.dmg`]: Buffer.from('dmg'),
    [`iamdirector-${V}-mac-arm64.zip`]: Buffer.from('PK'), [`iamdirector-${V}-mac-x64.zip`]: Buffer.from('PK'),
    [`iamdirector-${V}-win-x64.exe`]: Buffer.from('MZ'), [`iamdirector-${V}-win-arm64.exe`]: Buffer.from('MZ'),
    [`iamdirector-${V}-linux-x86_64.AppImage`]: elf(elfOverride.x64 || 'x64'),
    [`iamdirector-${V}-linux-arm64.AppImage`]: elf(elfOverride.arm64 || 'arm64'),
    [`iamdirector-${V}-linux-amd64.deb`]: Buffer.from('!<arch>'), [`iamdirector-${V}-linux-arm64.deb`]: Buffer.from('!<arch>'),
  };
  for (const [n, h] of Object.entries(files)) if (!skip.includes(n)) put(n, h);
  return d;
}
const debArch = (f) => (/arm64/.test(f) ? 'arm64' : 'x64');
const load = () => import('../scripts/release-manifest.mjs');

test('10 個安裝檔齊全：產生四份 latest*.yml 與 SHA-256 表', async () => {
  const { buildManifest } = await load();
  const m = buildManifest(fixture(), V, { debArch, minSize: 1 });
  assert.equal(m.count, 10);
  assert.deepEqual(Object.keys(m.yml).sort(), ['latest-linux-arm64.yml', 'latest-linux.yml', 'latest-mac.yml', 'latest.yml']);
  assert.match(m.yml['latest-mac.yml'], new RegExp(`^path: iamdirector-${V}-mac-arm64\\.zip$`, 'm'));
  assert.match(m.yml['latest.yml'], new RegExp(`^path: iamdirector-${V}-win-x64\\.exe$`, 'm'));
  assert.match(m.yml['latest-linux.yml'], /x86_64\.AppImage/);
  assert.match(m.yml['latest-linux-arm64.yml'], /arm64\.AppImage/);
  assert.equal(m.sums.split('\n').length, 12);
});

test('少一個檔就失敗（不能只發一部分）', async () => {
  const { buildManifest } = await load();
  assert.throws(() => buildManifest(fixture([`iamdirector-${V}-win-arm64.exe`]), V, { debArch, minSize: 1 }), /Windows exe/);
});

test('檔名寫 arm64、ELF 卻是 x86_64：擋下', async () => {
  const { buildManifest } = await load();
  assert.throws(() => buildManifest(fixture([], { arm64: 'x64' }), V, { debArch, minSize: 1 }), /ELF 是 x64/);
});

test('版本不符、檔案太小：擋下', async () => {
  const { buildManifest } = await load();
  assert.throws(() => buildManifest(fixture(), '1.0.0', { debArch, minSize: 1 }), /版本不是 1\.0\.0/);
  assert.throws(() => buildManifest(fixture(), V, { debArch }), /bytes/);
});
