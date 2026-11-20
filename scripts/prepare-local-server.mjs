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

const SERVER_FILES = [
  'local/studio_local.py', 'local/sqlite_store.py',
  'upstream.py', 'studio_store.py', 'studio_tools.py', 'storyboard.py', 'qc.py', 'page_strip.py',
  'export_spec.py', 'export_lambda/render.py', 'export_lambda/twist.py', 'scripts/export_local.py', 'templates.py',
  'cast_refs.py', 'shot_controls.py',
  'takes.py', 'gen_retry.py', 'local/agent_exec.py',
  // the whole filming/ package (tools/oss/export-oss.mjs fails if a .py in filming/ or postblocks/ at the commit is missing here; filming/self_improve.py is excluded there)
  'filming/__init__.py', 'filming/agent_cli.py', 'filming/agent_demo.py', 'filming/agent_loop.py', 'filming/blender.py',
  'filming/blockout.py', 'filming/blockout_frames.py', 'filming/camera_moves.py', 'filming/camera_path.py',
  'filming/camera_rigs.py', 'filming/contract.py', 'filming/dir_controls.py', 'filming/executor.py', 'filming/frames.py',
  'filming/inbox.py', 'filming/lock_qc.py', 'filming/long_plan.py', 'filming/plan_cli.py', 'filming/qc_report.py',
  'filming/registry.py', 'filming/scene.py', 'filming/shots.py', 'filming/ui_actions.py',
  'filming/ui_schema.py',
  'ui2.html',
  'previs/editor.js', 'previs/core.js', 'previs/vendor/three.module.min.js', 'previs/vendor/OrbitControls.js',
  'previs/vendor/TransformControls.js', 'previs/vendor/mp4-muxer.mjs',
  'approvals.py',
  'cli/appletoken/__init__.py',
  'cli/appletoken/core/__init__.py', 'cli/appletoken/core/api.py', 'cli/appletoken/core/errors.py',
  'cli/appletoken/core/http.py', 'cli/appletoken/core/model_caps.py', 'cli/appletoken/core/poll.py',
  'cli/appletoken/core/preflight.py',
  'cli/appletoken/core/redact.py', 'cli/appletoken/core/session.py',
  'cli/appletoken/mcp/__init__.py', 'cli/appletoken/mcp/activity.py', 'cli/appletoken/mcp/tools.py',
  'fonts/NotoSansTC-Bold.otf', 'fonts/OFL.txt', 'fonts/README.md',
  'export_lambda/postblocks/__init__.py', 'export_lambda/postblocks/audio_clip.py',
  'export_lambda/postblocks/audio_fade.py', 'export_lambda/postblocks/base.py',
  'export_lambda/postblocks/clip_trim.py', 'export_lambda/postblocks/compile.py',
  'export_lambda/postblocks/concat.py', 'export_lambda/postblocks/disclosure.py',
  'export_lambda/postblocks/encode.py', 'export_lambda/postblocks/fit.py', 'export_lambda/postblocks/fps.py',
  'export_lambda/postblocks/loudness.py', 'export_lambda/postblocks/meme_captions.py',
  'export_lambda/postblocks/mix.py', 'export_lambda/postblocks/music_duck.py',
  'export_lambda/postblocks/pad_black.py', 'export_lambda/postblocks/pure.py',
  'export_lambda/postblocks/subtitles.py', 'export_lambda/postblocks/titles.py',
  'export_lambda/postblocks/twist_detect.py', 'export_lambda/postblocks/video_fade.py',
  'export_lambda/postblocks/white_flash.py',
  'export_lambda/postblocks/format.py', 'export_lambda/postblocks/seam_check.py',
  'export_lambda/postblocks/subs.py', 'export_lambda/postblocks/transition.py',
  'export_lambda/postblocks/color_grade.py', 'export_lambda/postblocks/cover.py',
  'export_lambda/postblocks/speed.py', 'export_lambda/postblocks/watermark.py',
];
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

function syncCommitted() {
  const src = process.env.IAMDIRECTOR_LOCAL_SERVER_DIR;
  if (!src) throw new Error('--sync 要設 IAMDIRECTOR_LOCAL_SERVER_DIR（iamdirector repo）');
  fs.rmSync(COMMITTED, { recursive: true, force: true });
  for (const f of SERVER_FILES) {
    fs.mkdirSync(path.dirname(path.join(COMMITTED, f)), { recursive: true });
    fs.copyFileSync(path.join(src, f), path.join(COMMITTED, f));
  }
  const head = execFileSync('git', ['-C', src, 'rev-parse', '--short', 'HEAD']).toString().trim();
  fs.writeFileSync(path.join(COMMITTED, 'SOURCE_COMMIT'), head + '\n');
  console.log('local-server/ 已同步到 iamdirector ' + head);
}

function copyServer() {
  const src = process.env.IAMDIRECTOR_LOCAL_SERVER_DIR || COMMITTED;
  if (!fs.existsSync(path.join(src, 'local', 'studio_local.py'))) throw new Error('找不到本機伺服器的檔：' + src);
  const out = path.join(VENDOR, 'local-server');
  fs.rmSync(out, { recursive: true, force: true });
  for (const f of SERVER_FILES) {
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

function smoke(pyDir, serverDir) {
  const py = process.platform === 'win32' ? path.join(pyDir, 'python.exe') : path.join(pyDir, 'bin', 'python3');
  execFileSync(py, ['-I', '-B', '-c',
    'import sys; sys.path[:0]=[sys.argv[1]+"/local", sys.argv[1]]; import studio_local; print("ok")'
    // studio_local loads these lazily (export, cast refs): import them here so a missing file fails the build
    + '; import postblocks, cast_refs, shot_controls, takes, gen_retry, filming, agent_exec'
    + '; assert filming.__file__, "filming/__init__.py missing (namespace package)"'
    + '; import pkgutil, importlib; [importlib.import_module("filming." + m.name) for m in pkgutil.iter_modules(filming.__path__)]'
    + '; from filming import agent_loop, blockout_frames'
    + '; print("lazy modules ok")', serverDir],
  { stdio: 'inherit' });
  execFileSync(py, ['-I', '-B', '-c', [
    'import sys; sys.path.insert(0, sys.argv[1] + "/cli")',
    'from appletoken.core import Client, model_caps; from appletoken.core.session import Session',
    'from appletoken.mcp import tools as t',
    's = Session("x" * 40, base_url="http://127.0.0.1:1", kind="token", register=False)',
    'r = t.Registry(s, allow_spend=True, remote=True, local=True, client=Client(s))',
    'need = {"create_work", "quote", "request_approval", "submit_approved", "status", "result"}',
    'assert need <= set(r.names()), need - set(r.names())',
    'assert "appletoken.mcp.server" not in sys.modules and "mcp" not in sys.modules',
    'print("mcp tools ok:", len(r.names()))',
  ].join('\n'), serverDir], { stdio: 'inherit' });
}

if (process.argv.includes('--sync')) { syncCommitted(); process.exit(0); }
const arches = process.argv.slice(2).length ? process.argv.slice(2) : [process.arch];
const serverDir = copyServer();
for (const arch of arches) {
  const py = await fetchPython(process.platform, arch);
  if (arch === process.arch) smoke(py, serverDir);
  console.log(`python-${arch} 準備好了`);
}
