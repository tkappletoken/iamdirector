#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const distDir = process.argv[2] ?? 'dist';
const die = (m) => { console.error(`fix-mac-update-zip: ${m}`); process.exit(1); };
if (!existsSync(distDir)) die(`找不到 ${distDir}`);

const macDir = readdirSync(distDir).find((d) => d.startsWith('mac')
  && readdirSync(join(distDir, d)).some((f) => f.endsWith('.app')));
if (!macDir) die(`${distDir}/mac*/ 底下沒有 .app`);
const appPath = join(distDir, macDir, readdirSync(join(distDir, macDir)).find((f) => f.endsWith('.app')));
const zips = readdirSync(distDir).filter((f) => f.endsWith('.zip'));
if (zips.length !== 1) die(`${distDir} 應該剛好有一個 .zip，現在是 ${zips.length} 個`);
const zipName = zips[0];
const zipPath = join(distDir, zipName);
const ymlPath = join(distDir, 'latest-mac.yml');

execFileSync('ditto', ['-c', '-k', '--sequesterRsrc', '--keepParent', appPath, zipPath], { stdio: 'inherit' });
const buf = readFileSync(zipPath);
if (!existsSync(ymlPath)) { console.log(`fix-mac-update-zip: ${zipName} 已重包（沒有 latest-mac.yml，略過）`); process.exit(0); }
const sha512 = createHash('sha512').update(buf).digest('base64');

const lines = readFileSync(ymlPath, 'utf8').split('\n');
let inBlock = false, topIsZip = false, n = { fileSha: 0, fileSize: 0, topSha: 0 };
for (let i = 0; i < lines.length; i++) {
  const l = lines[i];
  if (/^path:\s*/.test(l)) topIsZip = l.includes(zipName);
  if (/^sha512:\s*/.test(l) && topIsZip) { lines[i] = `sha512: ${sha512}`; n.topSha++; }
  if (/^\s*-\s*url:\s*/.test(l)) inBlock = l.includes(zipName);
  else if (/^\s*-\s*/.test(l) || /^[a-zA-Z]/.test(l)) inBlock = false;
  if (inBlock && /^\s*sha512:\s*/.test(l)) { lines[i] = l.replace(/sha512:.*/, `sha512: ${sha512}`); n.fileSha++; }
  if (inBlock && /^\s*size:\s*/.test(l)) { lines[i] = l.replace(/size:.*/, `size: ${buf.length}`); n.fileSize++; }
}
if (!n.fileSha || !n.fileSize) die(`latest-mac.yml 找不到 ${zipName} 那一項（${JSON.stringify(n)}）`);
writeFileSync(ymlPath, lines.join('\n'));
console.log(`fix-mac-update-zip: ${zipName} size=${buf.length}`);
