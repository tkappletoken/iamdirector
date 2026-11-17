// Sync local-server/ from the iamdirector web repo at a given commit.
// Only the files listed in SERVER_FILES (scripts/prepare-local-server.mjs) are copied, and comments are removed;
// code is left byte-for-byte as is. Third-party vendor files are copied unchanged.
//
//   cd tools/oss && npm ci
//   node tools/oss/export-oss.mjs <web repo> <commit>
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import * as acorn from 'acorn';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const OUT = path.join(ROOT, 'local-server');

const [WEB, COMMIT] = process.argv.slice(2);
if (!WEB || !COMMIT) { console.error('usage: node tools/oss/export-oss.mjs <web repo> <commit>'); process.exit(2); }

const prep = fs.readFileSync(path.join(ROOT, 'scripts', 'prepare-local-server.mjs'), 'utf8');
const list = prep.match(/const SERVER_FILES = \[([\s\S]*?)\];/);
if (!list) throw new Error('SERVER_FILES not found in scripts/prepare-local-server.mjs');
const FILES = [...list[1].matchAll(/'([^']+)'/g)].map((m) => m[1]);
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
      return '';
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
fs.rmSync(OUT, { recursive: true, force: true });
for (const f of FILES) {
  const buf = execFileSync('git', ['-C', WEB, 'show', `${sha}:${f}`], { maxBuffer: 64 << 20 });
  const dst = path.join(OUT, f);
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.writeFileSync(dst, transform(f, buf));
}
fs.writeFileSync(path.join(OUT, 'SOURCE_COMMIT'), 'oss\n');
console.log(`local-server/: ${FILES.length} files from ${sha.slice(0, 7)}`);
