import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const VENDOR = path.join(ROOT, 'vendor');
const CACHE = path.join(VENDOR, '.cache');

const PBS_TAG = '20261026';
const PBS_VER = '3.12.16';
const PBS_SHA256 = {
  'aarch64-apple-darwin': 'fbf4afef53c2a6b72bb741bc06d5671a9dfaf87bd84e5aa73ac9b3d0d589f14e',
  'x86_64-apple-darwin': 'a962e47df522889eaa7ff0d6a56203f1079f68aabb65ffdbe8455f362bc769f3',
  'x86_64-pc-windows-msvc': '590dfcbe3a34c07301e6332e13e2188b98655cd072b08afa45a7998dc4c22bc5',
  'aarch64-pc-windows-msvc': 'ad585318bfe47980cbaa90be12a65319c5b4eec7472655428528068e710a6c9a',
  'x86_64-unknown-linux-gnu': '6a79e922e50006b601f29e688407659da1c2b86ebcd4e9c7254cf234be8b89de',
  'aarch64-unknown-linux-gnu': 'a945427411dc6851a1393533b74a4a1ac434321ae397f2ec69897a9b4fde032b',
};
const TRIPLE = {
  darwin: { arm64: 'aarch64-apple-darwin', x64: 'x86_64-apple-darwin' },
  win32: { arm64: 'aarch64-pc-windows-msvc', x64: 'x86_64-pc-windows-msvc' },
  linux: { arm64: 'aarch64-unknown-linux-gnu', x64: 'x86_64-unknown-linux-gnu' },
};

const PRUNE = ['test', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip', 'lib2to3', 'pydoc_data', 'unittest/test'];

function sha256(file) {
  return createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

async function fetchPython(platform, arch) {
  const triple = TRIPLE[platform]?.[arch];
  if (!triple) throw new Error(`不支援 ${platform}/${arch}`);
  const name = `cpython-${PBS_VER}+${PBS_TAG}-${triple}-install_only.tar.gz`;
  const file = path.join(CACHE, name);
  fs.mkdirSync(CACHE, { recursive: true });
  if (!fs.existsSync(file)) {
    const url = `https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${encodeURIComponent(name)}`;
    const res = await fetch(url, { redirect: 'follow' });
    if (!res.ok) throw new Error(`下載失敗 ${res.status}：${name}`);
    fs.writeFileSync(file + '.part', Buffer.from(await res.arrayBuffer()));
    fs.renameSync(file + '.part', file);
  }
  const got = sha256(file);
  if (got !== PBS_SHA256[triple]) {
    fs.rmSync(file, { force: true });
    throw new Error(`雜湊不符，已刪除：${name}`);
  }
  const out = path.join(VENDOR, `python-${arch}`);
  fs.rmSync(out, { recursive: true, force: true });
  fs.mkdirSync(out, { recursive: true });
  execFileSync('tar', ['-xzf', path.relative(out, file), '--strip-components=1'], { cwd: out });
  const lib = path.join(out, 'lib', 'python3.12');
  for (const p of PRUNE) fs.rmSync(path.join(lib, p), { recursive: true, force: true });
  fs.rmSync(path.join(out, 'include'), { recursive: true, force: true });
  return out;
}

const COMMITTED = path.join(ROOT, 'local-server');

// The file list comes from local/server_manifest.py in the source folder (the iamdirector repo keeps the only copy)
const pyBin = (pyDir) => (process.platform === 'win32' ? path.join(pyDir, 'python.exe') : path.join(pyDir, 'bin', 'python3'));
function serverFiles(pyDir, src) {
  return JSON.parse(execFileSync(pyBin(pyDir), ['-I', '-B', path.join(src, 'local', 'server_manifest.py'), '--json'],
    { encoding: 'utf8' })).files;
}

function syncCommitted(files) {
  const src = process.env.IAMDIRECTOR_LOCAL_SERVER_DIR;
  fs.rmSync(COMMITTED, { recursive: true, force: true });
  for (const f of files) {
    fs.mkdirSync(path.dirname(path.join(COMMITTED, f)), { recursive: true });
    fs.copyFileSync(path.join(src, f), path.join(COMMITTED, f));
  }
  const head = execFileSync('git', ['-C', src, 'rev-parse', '--short', 'HEAD']).toString().trim();
  fs.writeFileSync(path.join(COMMITTED, 'SOURCE_COMMIT'), head + '\n');
  console.log('local-server/ 已同步到 iamdirector ' + head);
}

function copyServer(src, files) {
  const out = path.join(VENDOR, 'local-server');
  fs.rmSync(out, { recursive: true, force: true });
  for (const f of files) {
    const to = path.join(out, f);
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.copyFileSync(path.join(src, f), to);
  }
  const commitFile = path.join(src, 'SOURCE_COMMIT');
  const head = fs.existsSync(commitFile) ? fs.readFileSync(commitFile, 'utf8').trim()
    : execFileSync('git', ['-C', src, 'rev-parse', '--short', 'HEAD']).toString().trim();
  fs.writeFileSync(path.join(out, 'SOURCE_COMMIT'), head + '\n');
  return out;
}

// local/smoke_packaged.py: every listed file is there and imports, no MCP SDK, the /mcp tool table, switches default off,
// and (when this arch's bundled ffmpeg is already in vendor/) an H.264 encoder
function smoke(pyDir, serverDir, arch) {
  const ff = path.join(VENDOR, `ffmpeg-${arch}`, process.platform === 'win32' ? 'ffmpeg.exe' : 'ffmpeg');
  execFileSync(pyBin(pyDir), ['-I', '-B', path.join(serverDir, 'local', 'smoke_packaged.py'), serverDir,
    ...(fs.existsSync(ff) ? ['--ffmpeg', ff] : []), '--json'], { stdio: 'inherit' });
}

const sync = process.argv.includes('--sync');
const src = process.env.IAMDIRECTOR_LOCAL_SERVER_DIR || (sync ? '' : COMMITTED);
if (!src) throw new Error('--sync 要設 IAMDIRECTOR_LOCAL_SERVER_DIR（iamdirector repo）');
if (!fs.existsSync(path.join(src, 'local', 'server_manifest.py'))) throw new Error('找不到 local/server_manifest.py：' + src);
const hostPy = await fetchPython(process.platform, process.arch);
const files = serverFiles(hostPy, src);
if (sync) { syncCommitted(files); process.exit(0); }
const arches = process.argv.slice(2).length ? process.argv.slice(2) : [process.arch];
const serverDir = copyServer(src, files);
for (const arch of arches) {
  if (arch === process.arch) smoke(hostPy, serverDir, arch);
  else await fetchPython(process.platform, arch);
  console.log(`python-${arch} 準備好了`);
}
