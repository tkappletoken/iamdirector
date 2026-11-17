// Start the bundled local server the way the app does (vendor/python-<arch> + vendor/local-server),
// with a fake key and an unreachable upstream, and check that GET / serves the page with the
// manifest injected. Run after scripts/prepare-local-server.mjs.
//
//   node scripts/smoke-local-server.mjs [arm64|x64]
import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const arch = process.argv[2] || process.arch;
const pyDir = path.join(ROOT, 'vendor', `python-${arch}`);
const py = process.platform === 'win32' ? path.join(pyDir, 'python.exe') : path.join(pyDir, 'bin', 'python3');
const server = path.join(ROOT, 'vendor', 'local-server', 'local', 'studio_local.py');
for (const f of [py, server]) if (!fs.existsSync(f)) { console.error(`missing ${f}`); process.exit(1); }

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'local-smoke-'));
const token = crypto.randomBytes(32).toString('hex');
const fakeKey = ['sk', 'smoke', crypto.randomBytes(8).toString('hex')].join('-');
const child = spawn(py, ['-I', '-B', server, '--data-dir', dataDir, '--gateway-base', 'http://127.0.0.1:9/v1'], {
  stdio: ['pipe', 'pipe', 'inherit'], env: { PATH: process.env.PATH || '', LANG: 'en_US.UTF-8', PYTHONIOENCODING: 'utf-8' },
});
let failed = false;
const fail = (m) => { console.error(`FAIL: ${m}`); failed = true; };
const done = () => { child.kill(); fs.rmSync(dataDir, { recursive: true, force: true }); process.exit(failed ? 1 : 0); };
const timer = setTimeout(() => { fail('local server did not report ready within 30 s'); done(); }, 30000);

let buf = '';
child.stdout.setEncoding('utf8');
child.stdout.on('data', async (chunk) => {
  buf += chunk;
  let i;
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i); buf = buf.slice(i + 1);
    let msg; try { msg = JSON.parse(line); } catch (_) { continue; }
    if (!msg.ready) continue;
    clearTimeout(timer);
    try {
      const res = await fetch(`http://127.0.0.1:${msg.port}/`, { headers: { 'X-Local-Token': token } });
      const body = await res.text();
      if (res.status !== 200) fail(`GET / returned ${res.status}: ${body.slice(0, 200)}`);
      if (!body.includes('window.__STUDIO__=')) fail('manifest was not injected (window.__STUDIO__ missing)');
      if (!/"local":\s*true/.test(body)) fail('manifest is not the local-mode manifest');
      if (body.includes('<!-- STUDIO-MANIFEST -->')) fail('slot is still in the page');
      if (!failed) console.log(`local server OK: GET / 200, ${body.length} bytes, manifest injected`);
    } catch (e) { fail(String(e)); }
    done();
  }
});
child.on('exit', (code) => { if (!failed) { fail(`local server exited (${code})`); } clearTimeout(timer); process.exit(1); });
child.stdin.write(JSON.stringify({ op: 'init', token, key: fakeKey, openh264_dir: null }) + '\n');
