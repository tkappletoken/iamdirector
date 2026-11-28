'use strict';
const crypto = require('node:crypto');
const path = require('node:path');

const READY_TIMEOUT_MS = 15000;

function resolveRuntime({ isPackaged, resourcesPath, env, platform, appRoot, arch, exists }) {
  if (isPackaged) {
    const py = platform === 'win32'
      ? path.join(resourcesPath, 'python', 'python.exe')
      : path.join(resourcesPath, 'python', 'bin', 'python3');
    return { python: py, server: path.join(resourcesPath, 'local-server', 'local', 'studio_local.py'),
      ffmpegDir: path.join(resourcesPath, 'ffmpeg') };
  }
  const dir = env.IAMDIRECTOR_LOCAL_SERVER_DIR;
  if (!dir) throw new Error('開發模式要設 IAMDIRECTOR_LOCAL_SERVER_DIR（指向 iamdirector repo）');
  return { python: env.IAMDIRECTOR_PYTHON || 'python3', server: path.join(dir, 'local', 'studio_local.py'),
    ffmpegDir: env.IAMDIRECTOR_FFMPEG_DIR || devFfmpegDir({ appRoot, arch, platform, exists }) };
}

// Dev mode without IAMDIRECTOR_FFMPEG_DIR: use the bundled LGPL build in vendor/ if it exists,
// otherwise the server falls back to PATH (e.g. Homebrew ffmpeg, which has no libass).
function devFfmpegDir({ appRoot, arch, platform, exists }) {
  if (!appRoot || !arch || !exists) return null;
  const dir = path.join(appRoot, 'vendor', 'ffmpeg-' + arch);
  return exists(path.join(dir, platform === 'win32' ? 'ffmpeg.exe' : 'ffmpeg')) ? dir : null;
}

// Feature switches the settings page may turn on for the local server (all default off).
// Only these names ever reach the server, and only from the app's own settings: the parent
// environment (e.g. launchctl setenv) is not read for them.
// 0.2.24: dubbing / lip-sync (cost money). 0.2.26: previs blocking -> director controls for the Agent,
// per-shot first/last frames for work_run (generation still goes through approval cards), mute model audio on merge.
// 0.2.27: chat-as-interface (UI v2 B, phase 1): the chat panel and the external Agent's chat_post / chat_inbox MCP tools.
const SERVER_FLAGS = Object.freeze(['STUDIO_TTS_FIRST', 'STUDIO_VOICE_LINE', 'STUDIO_LIPSYNC_SHOT',
  'STUDIO_LOCAL_BLOCKING_SYNC', 'STUDIO_WORK_FRAMES', 'STUDIO_MUTE_MODEL_AUDIO', 'STUDIO_UI_V2_CHAT']);

// settings.json value -> { NAME: boolean } for exactly the whitelisted names (missing/invalid = false).
function pickFlags(saved) {
  const src = saved && typeof saved === 'object' ? saved : {};
  const out = {};
  for (const k of SERVER_FLAGS) out[k] = Object.prototype.hasOwnProperty.call(src, k) && src[k] === true;
  return out;
}

// IMAGE_RECOVER (off|shadow|on): the server defaults to off; the desktop app ships shadow
// (log-only) unless the user's environment sets it.
function serverEnv(parent, flags) {
  const env = { PATH: parent.PATH || '', LANG: 'en_US.UTF-8', PYTHONIOENCODING: 'utf-8',
    IMAGE_RECOVER: parent.IMAGE_RECOVER || 'shadow' };
  const on = pickFlags(flags);
  for (const k of SERVER_FLAGS) if (on[k]) env[k] = 'on';
  return env;
}

function start({ spawn, runtime, dataDir, keystore, gatewayBase, onExit, openh264Dir, flags }) {
  const token = crypto.randomBytes(32).toString('hex');
  let initialKey = null;
  try { initialKey = keystore.load() || null; } catch (_) { initialKey = null; }
  const args = ['-I', '-B', runtime.server, '--data-dir', dataDir];
  if (gatewayBase) args.push('--gateway-base', gatewayBase);
  if (runtime.ffmpegDir) args.push('--ffmpeg-dir', runtime.ffmpegDir);
  const child = spawn(runtime.python, args, {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: serverEnv(process.env, flags),
    windowsHide: true,
  });
  let buf = '';
  let readyResolve; let readyReject;
  const ready = new Promise((ok, bad) => { readyResolve = ok; readyReject = bad; });
  ready.catch(() => {});
  const timer = setTimeout(() => readyReject(new Error('本機伺服器沒有在時限內啟動')), READY_TIMEOUT_MS);
  let errLines = 0;
  const waiting = new Map();
  let seq = 0;
  child.stdin.on('error', () => {});
  const send = (obj) => {
    if (child.exitCode !== null || child.stdin.destroyed) return;
    try { child.stdin.write(JSON.stringify(obj) + '\n'); } catch (_) {}
  };

  function onMessage(msg) {
    if (msg.ready && Number.isInteger(msg.port)) { clearTimeout(timer); readyResolve(msg.port); return; }
    if (msg.op === 'store_key' && typeof msg.key === 'string') {
      let r;
      try { r = keystore.save(msg.key); } catch (_) { r = { persisted: false, reason: 'invalid' }; }
      send({ op: 'store_result', id: msg.id, persisted: !!r.persisted, reason: r.reason || null });
      return;
    }
    if (msg.op === 'clear_key') { keystore.clear(); send({ op: 'clear_result', id: msg.id, ok: true }); }
    if (msg.op === 'openh264_result' && waiting.has(msg.id)) { waiting.get(msg.id)(msg.ok === true); waiting.delete(msg.id); }
  }

  child.stdout.setEncoding('utf8');
  child.stdout.on('data', (chunk) => {
    buf += chunk;
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i); buf = buf.slice(i + 1);
      let msg; try { msg = JSON.parse(line); } catch (_) { continue; }
      if (msg && typeof msg === 'object') onMessage(msg);
    }
  });
  child.stderr.on('data', () => { errLines += 1; });
  child.on('error', (err) => { clearTimeout(timer); readyReject(err); });
  child.on('exit', (code) => {
    clearTimeout(timer);
    readyReject(new Error('本機伺服器結束了（' + code + '）'));
    if (onExit) onExit(code);
  });

  send({ op: 'init', token, key: initialKey, openh264_dir: openh264Dir || null });

  return {
    token,
    ready,
    pid: child.pid,
    errors: () => errLines,
    setOpenH264: (dir) => new Promise((ok) => {
      const id = ++seq;
      const t = setTimeout(() => { waiting.delete(id); ok(false); }, 15000);
      waiting.set(id, (v) => { clearTimeout(t); ok(v); });
      send({ op: 'set_openh264', id, dir: dir || null });
    }),
    stop: () => { try { child.stdin.end(); } catch (_) {} try { child.kill(); } catch (_) {} },
  };
}

function needsToken(url, port) {
  try {
    const u = new URL(url);
    return u.protocol === 'http:' && u.hostname === '127.0.0.1' && Number(u.port) === port;
  } catch (_) { return false; }
}

function gatewayOverride(value, isPackaged) {
  if (!value) return null;
  if (!isPackaged) return value;
  return /^http:\/\/127\.0\.0\.1:\d{1,5}\/[A-Za-z0-9/_-]*$/.test(value) ? value : null;
}

module.exports = { resolveRuntime, serverEnv, pickFlags, SERVER_FLAGS, start, needsToken, gatewayOverride, TOKEN_HEADER: 'X-Local-Token' };
