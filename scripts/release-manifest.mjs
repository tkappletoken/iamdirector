#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync, statSync, writeFileSync, openSync, readSync, closeSync } from 'node:fs';
import { join, basename } from 'node:path';
import { fileURLToPath } from 'node:url';

const MIN_SIZE = 50 * 1024 * 1024;
const ARM = /(arm64|aarch64)/;
const X64 = /(x64|x86_64|amd64)/;

function head(file, n) {
  const fd = openSync(file, 'r');
  try { const b = Buffer.alloc(n); readSync(fd, b, 0, n, 0); return b; } finally { closeSync(fd); }
}

function nameArch(f) {
  const n = basename(f);
  if (ARM.test(n)) return 'arm64';
  if (X64.test(n)) return 'x64';
  return null;
}

function elfArch(file) {
  const b = head(file, 20);
  if (b.readUInt32BE(0) !== 0x7f454c46) throw new Error(`${basename(file)} 不是 ELF`);
  const m = b.readUInt16LE(18);
  return m === 62 ? 'x64' : m === 183 ? 'arm64' : `e_machine=${m}`;
}

function debArchDefault(file) {
  const a = execFileSync('dpkg-deb', ['-f', file, 'Architecture'], { encoding: 'utf8' }).trim();
  return a === 'amd64' ? 'x64' : a;
}

const sha = (algo, buf, enc) => createHash(algo).update(buf).digest(enc);

export function buildManifest(dist, version, { debArch = debArchDefault, minSize = MIN_SIZE } = {}) {
  const files = readdirSync(dist).filter((f) => statSync(join(dist, f)).isFile());
  const pick = (ext) => files.filter((f) => f.endsWith(ext)).map((f) => join(dist, f));
  const groups = {
    'mac dmg': pick('.dmg'), 'mac zip': pick('.zip'),
    'Windows exe': pick('.exe'), 'Linux AppImage': pick('.AppImage'), 'Linux deb': pick('.deb'),
  };
  const errors = [];
  for (const [g, list] of Object.entries(groups)) {
    const archs = list.map(nameArch).sort();
    if (list.length !== 2 || archs.join() !== 'arm64,x64') {
      errors.push(`${g} 要剛好 arm64、x64 各一個，現在是 ${list.map((f) => basename(f)).join('、') || '沒有'}`);
    }
    for (const f of list) {
      if (!basename(f).includes(`-${version}-`)) errors.push(`${basename(f)} 的版本不是 ${version}`);
      if (statSync(f).size < minSize) errors.push(`${basename(f)} 只有 ${statSync(f).size} bytes`);
    }
  }
  for (const f of groups['Linux AppImage']) {
    const a = elfArch(f); if (a !== nameArch(f)) errors.push(`${basename(f)} 檔名是 ${nameArch(f)}，ELF 是 ${a}`);
  }
  for (const f of groups['Linux deb']) {
    const a = debArch(f); if (a !== nameArch(f)) errors.push(`${basename(f)} 檔名是 ${nameArch(f)}，deb 是 ${a}`);
  }
  for (const f of groups['Windows exe']) {
    if (head(f, 2).toString('latin1') !== 'MZ') errors.push(`${basename(f)} 不是 Windows 執行檔`);
  }
  if (errors.length) throw new Error('發佈前檢查沒過：\n- ' + errors.join('\n- '));

  const info = (f) => { const b = readFileSync(f); return { f, url: basename(f), size: b.length, sha512: sha('sha512', b, 'base64'), sha256: sha('sha256', b, 'hex') }; };
  const byArch = (list) => [...list].sort((a, b) => (nameArch(a) === 'x64' ? -1 : 1) - (nameArch(b) === 'x64' ? -1 : 1)).map(info);
  const date = new Date().toISOString();
  const yml = (entries, primary) => [`version: ${version}`, 'files:',
    ...entries.flatMap((e) => [`  - url: ${e.url}`, `    sha512: ${e.sha512}`, `    size: ${e.size}`]),
    `path: ${primary.url}`, `sha512: ${primary.sha512}`, `releaseDate: '${date}'`, ''].join('\n');

  const mac = [...byArch(groups['mac zip']), ...byArch(groups['mac dmg'])];
  const win = byArch(groups['Windows exe']);
  const app = byArch(groups['Linux AppImage']);
  const out = {
    'latest-mac.yml': yml(mac, mac.find((e) => nameArch(e.f) === 'arm64' && e.url.endsWith('.zip'))),
    'latest.yml': yml(win, win[0]),
    'latest-linux.yml': yml([app[0]], app[0]),
    'latest-linux-arm64.yml': yml([app[1]], app[1]),
  };
  const all = [...byArch(groups['mac dmg']), ...byArch(groups['mac zip']), ...win, ...app, ...byArch(groups['Linux deb'])];
  const sums = ['| 檔案 · File | SHA-256 |', '|---|---|', ...all.map((e) => `| \`${e.url}\` | \`${e.sha256}\` |`)].join('\n');
  return { yml: out, sums, count: all.length };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const [dist, version, sumsOut] = process.argv.slice(2);
  if (!dist || !version || !sumsOut) { console.error('用法：release-manifest.mjs <distDir> <version> <sha256 輸出檔>'); process.exit(2); }
  try {
    const m = buildManifest(dist, version);
    for (const [n, body] of Object.entries(m.yml)) writeFileSync(join(dist, n), body);
    writeFileSync(sumsOut, m.sums + '\n');
    console.log(`release-manifest: ${m.count} 個安裝檔通過檢查，產生 ${Object.keys(m.yml).join('、')}`);
    console.log(m.sums);
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
}
