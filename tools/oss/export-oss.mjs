// Sync local-server/ from the iamdirector web repo at a given commit.
// Only the files listed by local/server_manifest.py at that commit are copied, and comments are removed;
// code is left byte-for-byte as is. Third-party vendor files are copied unchanged.
// The developer guide (docs/desktop-oss-guide.md) is copied unchanged to docs/DEVELOPERS.md.
//
//   cd tools/oss && npm ci
//   node tools/oss/export-oss.mjs <web repo> <commit>
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import * as acorn from 'acorn';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const OUT = path.join(ROOT, 'local-server');

const [WEB, COMMIT] = process.argv.slice(2);
if (!WEB || !COMMIT) { console.error('usage: node tools/oss/export-oss.mjs <web repo> <commit>'); process.exit(2); }

const KEEP_AS_IS = [/\/vendor\//, /\.min\.js$/];

// Cut [start, end) ranges; drop the whole line when nothing else is on it, otherwise also the whitespace before it
function cut(src, ranges) {
  ranges.sort((a, b) => a[0] - b[0]);
  let out = ''; let pos = 0;
  for (let [s, e] of ranges) {
    if (s < pos) continue;
    const ls = src.lastIndexOf('\n', s - 1) + 1;
    let le = src.indexOf('\n', e); if (le < 0) le = src.length;
    const before = src.slice(ls, s); const after = src.slice(e, le);
    if (!before.trim() && !after.trim()) { s = ls; e = le < src.length ? le + 1 : le; }
    else { while (s > ls && /[ \t]/.test(src[s - 1])) s--; }
    out += src.slice(pos, s); pos = e;
  }
  return (out + src.slice(pos)).replace(/\n{3,}/g, '\n\n');
}

function stripJs(src, sourceType) {
  const ranges = [];
  let body = src; let shebang = '';
  if (body.startsWith('#!')) { const i = body.indexOf('\n'); shebang = body.slice(0, i + 1); body = body.slice(i + 1); }
  acorn.parse(body, {
    ecmaVersion: 'latest', sourceType, allowHashBang: true, allowReturnOutsideFunction: true,
    allowAwaitOutsideFunction: true, onComment: (block, text, s, e) => ranges.push([s, e]),
  });
  return shebang + cut(body, ranges);
}
function jsAuto(src) {
  try { return stripJs(src, 'script'); } catch (_) { return stripJs(src, 'module'); }
}

function stripPy(src) {
  return execFileSync('python3', ['-I', path.join(HERE, 'strip_py.py')],
    { input: src, encoding: 'utf8', maxBuffer: 64 << 20 });
}

function stripHtml(src) {
  return src.replace(/(<script\b[^>]*>)([\s\S]*?)(<\/script>)|(<style\b[^>]*>)([\s\S]*?)(<\/style>)|<!--[\s\S]*?-->/g,
    (m, so, js, sc, to, css, tc) => {
      if (so !== undefined) {
        if (/type="application\/(ld\+)?json"/.test(so) || !js.trim()) return m;
        return so + stripJs(js, /type="module"/.test(so) ? 'module' : 'script') + sc;
      }
      if (to !== undefined) return to + cut(css, [...css.matchAll(/\/\*[\s\S]*?\*\//g)].map((x) => [x.index, x.index + x[0].length])) + tc;
      return /^<!--\s*[A-Z][A-Z0-9-]*\s*-->$/.test(m) ? m : '';   // keep template slots such as <!-- STUDIO-MANIFEST -->
    });
}

function transform(f, buf) {
  if (KEEP_AS_IS.some((r) => r.test(f))) return buf;
  const ext = path.extname(f); const s = buf.toString('utf8');
  if (ext === '.js' || ext === '.cjs') return Buffer.from(jsAuto(s));
  if (ext === '.mjs') return Buffer.from(stripJs(s, 'module'));
  if (ext === '.py') return Buffer.from(stripPy(s));
  if (ext === '.html') return Buffer.from(stripHtml(s));
  return buf;
}

const sha = execFileSync('git', ['-C', WEB, 'rev-parse', '--verify', `${COMMIT}^{commit}`], { encoding: 'utf8' }).trim();
// The file list is local/server_manifest.py run on a clean tree of that commit (it walks its own tree, not the web checkout)
const TREE = fs.mkdtempSync(path.join(os.tmpdir(), 'export-oss-'));
let FILES, NOT_PACKED;
// Public but not packed into the app: developer tools the guide refers to (each must be in the manifest's not_packed)
const PUBLIC_ONLY = ['local/dev_fake_upstream.py'];
try {
  execFileSync('tar', ['-x', '-C', TREE], { input: execFileSync('git', ['-C', WEB, 'archive', sha], { maxBuffer: 1 << 30 }) });
  if (!fs.existsSync(path.join(TREE, 'local', 'server_manifest.py'))) throw new Error(`no local/server_manifest.py at ${sha.slice(0, 7)}`);
  ({ files: FILES, not_packed: NOT_PACKED } = JSON.parse(execFileSync('python3',
    ['-I', '-B', path.join(TREE, 'local', 'server_manifest.py'), '--json'], { encoding: 'utf8' })));
} finally {
  fs.rmSync(TREE, { recursive: true, force: true });
}
// Packages imported as a whole: every .py in them has to ship, or an import fails only when the feature is used
// Not shipped: self_improve.py is a production ops tool (instance id, AWS profile, host paths); nothing here imports it
const NOT_SHIPPED = ['filming/self_improve.py'];
const shipped = NOT_SHIPPED.filter((f) => FILES.includes(f));
if (shipped.length) throw new Error('must not be in the manifest: ' + shipped.join(', '));
const missing = ['filming', 'export_lambda/postblocks'].flatMap((dir) =>
  execFileSync('git', ['-C', WEB, 'ls-tree', '--name-only', `${sha}:${dir}`], { encoding: 'utf8' })
    .split('\n').filter((n) => n.endsWith('.py')).map((n) => dir + '/' + n)).filter((f) => !FILES.includes(f) && !NOT_SHIPPED.includes(f));
if (missing.length) throw new Error('not in the manifest: ' + missing.join(', '));
// Docstrings and strings ship verbatim, so the final output is scanned before anything is written.
// INTERNAL_NAMES matches tests/test_oss_clean.py in the web repo
const INTERNAL_NAMES = ['導演指揮', '指揮線', 'Appletoken指揮', '模組化畫面', '模組化M2', 'M2生成', '導演控制後端', '影片助手',
  '桌面-', '網頁-', '共用-', 'Navide', 'navide', 'Dudu', 'Nini', 'dudunini'];
const LEAKS = {
  'instance id': /\bi-0[0-9a-f]{8,17}\b/g,
  'host path': /\/Users\/[^/\s"']+/g,
  'AWS region': /\b(?:us|eu|ap|sa|ca|me|af|il)-(?:north|south|east|west|central|northeast|northwest|southeast|southwest)-\d\b/g,
  'AWS account': /arn:aws:[a-z0-9-]*:[a-z0-9-]*:\d{12}/g,
  'internal name': new RegExp(INTERNAL_NAMES.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'g'),
};
const notListed = PUBLIC_ONLY.filter((f) => !(f in NOT_PACKED));
if (notListed.length) throw new Error('public-only files must be in the manifest not_packed: ' + notListed.join(', '));
const out = [...FILES, ...PUBLIC_ONLY].map((f) => [f, transform(f, execFileSync('git', ['-C', WEB, 'show', `${sha}:${f}`], { maxBuffer: 64 << 20 }))]);
const GUIDE = 'docs/desktop-oss-guide.md';
const guide = execFileSync('git', ['-C', WEB, 'show', `${sha}:${GUIDE}`], { maxBuffer: 64 << 20 });
const leaks = [];
for (const [f, buf] of [...out, [GUIDE, guide]]) {
  if (KEEP_AS_IS.some((r) => r.test(f)) || buf.includes(0)) continue;
  buf.toString('utf8').split('\n').forEach((line, i) => {
    for (const [kind, rx] of Object.entries(LEAKS)) for (const m of line.matchAll(rx)) leaks.push(`${f}:${i + 1} ${kind} "${m[0]}"`);
  });
}
if (leaks.length) throw new Error('internal info in shipped files:\n' + leaks.join('\n'));
fs.rmSync(OUT, { recursive: true, force: true });
for (const [f, buf] of out) {
  const dst = path.join(OUT, f);
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.writeFileSync(dst, buf);
}
fs.writeFileSync(path.join(OUT, 'SOURCE_COMMIT'), 'oss\n');
fs.mkdirSync(path.join(ROOT, 'docs'), { recursive: true });
fs.writeFileSync(path.join(ROOT, 'docs', 'DEVELOPERS.md'), guide);
console.log(`local-server/: ${FILES.length} files + ${PUBLIC_ONLY.length} public-only from ${sha.slice(0, 7)}; docs/DEVELOPERS.md from ${GUIDE}`);
