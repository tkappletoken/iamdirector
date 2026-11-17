#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const env = { ...process.env };
const has = (k) => typeof env[k] === 'string' && env[k].trim() !== '';
const NOTARY = ['APPLE_API_KEY', 'APPLE_API_KEY_ID', 'APPLE_API_ISSUER'];

const arch = env.MAC_ARCH || 'arm64';
if (!['arm64', 'x64'].includes(arch)) { console.error(`dist-mac: MAC_ARCH 只能是 arm64 或 x64：${arch}`); process.exit(2); }
const noFfmpeg = process.env.BUILD_CHECK_NO_FFMPEG === '1';
for (const need of [`vendor/python-${arch}/bin/python3`, 'vendor/local-server/local/studio_local.py',
  ...(noFfmpeg ? [] : [`vendor/ffmpeg-${arch}/ffmpeg`, `vendor/ffmpeg-${arch}/ffprobe`])]) {
  if (!fs.existsSync(path.join(root, need))) {
    console.error(`dist-mac: 缺 ${need}；先跑 npm run prepare:local -- ${arch}` +
      ` 與 bash scripts/build-ffmpeg-lgpl.sh ${arch === 'x64' ? 'x86_64' : arch}`);
    process.exit(2);
  }
}
const args = ['--mac', 'dmg', 'zip', `--${arch}`, '--publish', 'never'];
let mode;
if (has('CSC_LINK')) {
  const missing = NOTARY.filter((k) => !has(k));
  if (missing.length === NOTARY.length) {
    mode = 'Developer ID 簽章，不公證（沒有 APPLE_API_*）';
  } else if (missing.length) {
    console.error(`dist-mac: 公證變數缺 ${missing.join('、')}（三個要一起給）`);
    process.exit(2);
  } else {
    mode = 'Developer ID 簽章＋公證';
    args.push('-c.mac.notarize=true');
  }
  if (env.REQUIRE_NOTARIZE === '1' && missing.length) {
    console.error('dist-mac: REQUIRE_NOTARIZE=1 但沒有公證變數，拒絕產出未公證的正式版');
    process.exit(2);
  }
} else {
  if (env.REQUIRE_NOTARIZE === '1') {
    console.error('dist-mac: REQUIRE_NOTARIZE=1 但沒有 CSC_LINK，拒絕退回 ad-hoc');
    process.exit(2);
  }
  mode = 'ad-hoc 簽章（沒有 CSC_LINK）';
  env.CSC_IDENTITY_AUTO_DISCOVERY = 'false';
  args.push('-c.mac.identity=-', '-c.mac.hardenedRuntime=false');
}
args.push(...process.argv.slice(2));
console.log(`dist-mac: ${mode}（${arch}）`);

const bin = path.join(root, 'node_modules', '.bin', 'electron-builder');
const r = spawnSync(bin, args, { cwd: root, env, stdio: 'inherit' });
process.exit(r.status ?? 1);
