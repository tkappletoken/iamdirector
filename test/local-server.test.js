'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const os = require('node:os');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const ls = require('../src/local-server');

const DIR = process.env.IAMDIRECTOR_LOCAL_SERVER_DIR;
const GOOD = ['at', 'desk', crypto.randomBytes(10).toString('hex')].join('-');

function fakeUpstream() {
  return new Promise((ok) => {
    const srv = http.createServer((req, res) => {
      const auth = req.headers.authorization === 'Bearer ' + GOOD;
      res.setHeader('Content-Type', 'application/json');
      if (!auth) { res.statusCode = 401; res.end('{"error":{"code":"invalid_api_key"}}'); return; }
      res.end(req.url === '/v2/me' ? '{"available":1}' : '{"data":[]}');
    });
    srv.listen(0, '127.0.0.1', () => ok(srv));
  });
}

function memKeystore() {
  const box = { saved: null, cleared: 0 };
  return {
    box,
    load: () => box.saved,
    save: (k) => { box.saved = k; return { persisted: true, last4: k.slice(-4) }; },
    clear: () => { box.saved = null; box.cleared += 1; },
  };
}

test('needsToken：只有本機伺服器自己的 origin', () => {
  assert.ok(ls.needsToken('http://127.0.0.1:5000/api/x', 5000));
  assert.ok(!ls.needsToken('http://127.0.0.1:5001/api/x', 5000));
  assert.ok(!ls.needsToken('https://iamdirector.app/api/x', 5000));
  assert.ok(!ls.needsToken('http://localhost:5000/api/x', 5000));
});

test('gatewayOverride：打包版只收 127.0.0.1 的 http，其他當作沒設', () => {
  assert.equal(ls.gatewayOverride('http://127.0.0.1:18901/v2', true), 'http://127.0.0.1:18901/v2');
  for (const bad of ['http://evil.example/v2', 'https://evil.example/v2', 'http://localhost:1/v2', 'http://127.0.0.1.evil.com:1/v2', 'http://127.0.0.1:1@evil.com/v2']) {
    assert.equal(ls.gatewayOverride(bad, true), null, bad);
  }
  assert.equal(ls.gatewayOverride('https://staging.example/v2', false), 'https://staging.example/v2');
  assert.equal(ls.gatewayOverride('', true), null);
});

test('resolveRuntime：打包版用附帶的 python；開發版沒設路徑就直接炸', () => {
  const r = ls.resolveRuntime({ isPackaged: true, resourcesPath: '/R', env: {}, platform: 'darwin' });
  assert.equal(r.python, path.join('/R', 'python', 'bin', 'python3'));
  assert.equal(r.ffmpegDir, path.join('/R', 'ffmpeg'), '打包版用附帶的 LGPL ffmpeg');
  assert.throws(() => ls.resolveRuntime({ isPackaged: false, env: {}, platform: 'darwin' }));
});

test('resolveRuntime：開發版沒設 IAMDIRECTOR_FFMPEG_DIR 時用 vendor/ffmpeg-<arch>；打包版不變', () => {
  const env = { IAMDIRECTOR_LOCAL_SERVER_DIR: '/W' };
  const dir = path.join('/A', 'vendor', 'ffmpeg-arm64');
  const has = (p) => p === path.join(dir, 'ffmpeg');
  const dev = (e, exists) => ls.resolveRuntime({ isPackaged: false, env: e, platform: 'darwin', appRoot: '/A', arch: 'arm64', exists });
  assert.equal(dev(env, has).ffmpegDir, dir);
  assert.equal(dev(env, () => false).ffmpegDir, null, 'vendor 裡沒有就照舊走 PATH');
  assert.equal(dev({ ...env, IAMDIRECTOR_FFMPEG_DIR: '/F' }, has).ffmpegDir, '/F', '環境變數優先');
  assert.equal(ls.resolveRuntime({ isPackaged: false, env, platform: 'darwin' }).ffmpegDir, null);
  const pk = ls.resolveRuntime({ isPackaged: true, resourcesPath: '/R', env: { IAMDIRECTOR_FFMPEG_DIR: '/F' }, platform: 'darwin', appRoot: '/A', arch: 'arm64', exists: has });
  assert.equal(pk.ffmpegDir, path.join('/R', 'ffmpeg'), '打包版一律用附帶的');
});

test('serverEnv：IMAGE_RECOVER 沒設預設 shadow；有設以環境變數為準；不帶其他變數', () => {
  assert.equal(ls.serverEnv({ PATH: '/bin' }).IMAGE_RECOVER, 'shadow');
  assert.equal(ls.serverEnv({ PATH: '/bin', IMAGE_RECOVER: 'on' }).IMAGE_RECOVER, 'on');
  assert.equal(ls.serverEnv({ PATH: '/bin', IMAGE_RECOVER: 'off' }).IMAGE_RECOVER, 'off');
  assert.deepEqual(Object.keys(ls.serverEnv({ PATH: '/bin', SECRET_X: 'x' })).sort(),
    ['IMAGE_RECOVER', 'LANG', 'PATH', 'PYTHONIOENCODING']);
});

test('serverFlags：預設全關＝環境變數跟以前一模一樣（沒帶、空的、全 false 都一樣）', () => {
  const base = ls.serverEnv({ PATH: '/bin' });
  const allOff = Object.fromEntries(ls.SERVER_FLAGS.map(k => [k, false]));
  for (const flags of [undefined, null, {}, { STUDIO_TTS_FIRST: false, STUDIO_VOICE_LINE: false, STUDIO_LIPSYNC_SHOT: false }, allOff]) {
    assert.deepEqual(ls.serverEnv({ PATH: '/bin' }, flags), base, JSON.stringify(flags));
  }
  assert.deepEqual(Object.keys(base).sort(), ['IMAGE_RECOVER', 'LANG', 'PATH', 'PYTHONIOENCODING']);
});

test('serverFlags：白名單只有這七個，打開的才帶 on；其他鍵、非 true 的值一律不帶', () => {
  // 0.2.24 三個（配音與對嘴）＋ 0.2.26 三個（場面調度站位換算、每鏡首尾幀、合併時原聲靜音）＋ 0.2.27 一個（對話即介面）
  assert.deepEqual([...ls.SERVER_FLAGS].sort(), ['STUDIO_LIPSYNC_SHOT', 'STUDIO_LOCAL_BLOCKING_SYNC', 'STUDIO_MUTE_MODEL_AUDIO',
    'STUDIO_TTS_FIRST', 'STUDIO_UI_V2_CHAT', 'STUDIO_VOICE_LINE', 'STUDIO_WORK_FRAMES']);
  const env = ls.serverEnv({ PATH: '/bin' }, { STUDIO_TTS_FIRST: true, STUDIO_VOICE_LINE: 'on', STUDIO_LIPSYNC_SHOT: 1,
    STUDIO_LOCAL_MCP_DIRECT: true, SECRET_X: true, __proto__: { STUDIO_TTS_FIRST: true } });
  assert.equal(env.STUDIO_TTS_FIRST, 'on');
  assert.equal(env.STUDIO_VOICE_LINE, undefined, '只認 true，字串 on 不算');
  assert.equal(env.STUDIO_LIPSYNC_SHOT, undefined);
  assert.equal(env.STUDIO_LOCAL_MCP_DIRECT, undefined, '白名單以外的不帶');
  assert.equal(env.SECRET_X, undefined);
  assert.deepEqual(Object.keys(env).sort(), ['IMAGE_RECOVER', 'LANG', 'PATH', 'PYTHONIOENCODING', 'STUDIO_TTS_FIRST']);
});

test('serverFlags：0.2.26 的三個各自只帶自己那一個；開關以外的本機開關（主迴圈、首幀接力…走 App 設定檔）照舊不帶', () => {
  for (const k of ['STUDIO_LOCAL_BLOCKING_SYNC', 'STUDIO_WORK_FRAMES', 'STUDIO_MUTE_MODEL_AUDIO']) {
    const env = ls.serverEnv({ PATH: '/bin' }, { [k]: true });
    assert.deepEqual(Object.keys(env).sort(), ['IMAGE_RECOVER', 'LANG', 'PATH', 'PYTHONIOENCODING', k].sort(), k);
    assert.equal(env[k], 'on', k);
  }
  const env = ls.serverEnv({ PATH: '/bin' }, { STUDIO_LOCAL_AGENT_LOOP: true, STUDIO_LOCAL_FRAME_RELAY: true, STUDIO_CAST_REFS: true,
    STUDIO_BLOCKOUT_FRAMES: true, STUDIO_AUTO_TAKES: true, STUDIO_DIALOGUE_TEMPLATE: true });
  assert.deepEqual(Object.keys(env).sort(), ['IMAGE_RECOVER', 'LANG', 'PATH', 'PYTHONIOENCODING']);
});

test('serverFlags：0.2.27 的對話即介面（STUDIO_UI_V2_CHAT）只帶自己那一個、只認 true', () => {
  const env = ls.serverEnv({ PATH: '/bin' }, { STUDIO_UI_V2_CHAT: true });
  assert.deepEqual(Object.keys(env).sort(), ['IMAGE_RECOVER', 'LANG', 'PATH', 'PYTHONIOENCODING', 'STUDIO_UI_V2_CHAT']);
  assert.equal(env.STUDIO_UI_V2_CHAT, 'on');
  for (const v of ['on', 1, 'true', null]) {
    assert.equal(ls.serverEnv({ PATH: '/bin' }, { STUDIO_UI_V2_CHAT: v }).STUDIO_UI_V2_CHAT, undefined, String(v));
  }
});

test('serverFlags：值只從設定來，不讀父程序的環境變數（launchctl setenv 不算）', () => {
  const parent = { PATH: '/bin', STUDIO_TTS_FIRST: 'on', STUDIO_VOICE_LINE: 'on', STUDIO_LIPSYNC_SHOT: 'on',
    STUDIO_LOCAL_BLOCKING_SYNC: 'on', STUDIO_WORK_FRAMES: 'on', STUDIO_MUTE_MODEL_AUDIO: 'on', STUDIO_UI_V2_CHAT: 'on' };
  assert.deepEqual(ls.serverEnv(parent), ls.serverEnv({ PATH: '/bin' }));
  assert.deepEqual(ls.serverEnv(parent, { STUDIO_VOICE_LINE: true }).STUDIO_TTS_FIRST, undefined);
});

test('pickFlags：設定檔讀回來只留白名單的布林值，缺的補 false', () => {
  const none = { STUDIO_TTS_FIRST: false, STUDIO_VOICE_LINE: false, STUDIO_LIPSYNC_SHOT: false,
    STUDIO_LOCAL_BLOCKING_SYNC: false, STUDIO_WORK_FRAMES: false, STUDIO_MUTE_MODEL_AUDIO: false, STUDIO_UI_V2_CHAT: false };
  assert.deepEqual(ls.pickFlags(undefined), none);
  assert.deepEqual(ls.pickFlags({ STUDIO_VOICE_LINE: true, STUDIO_TTS_FIRST: 'yes', STUDIO_WORK_FRAMES: 1, OTHER: true }),
    { ...none, STUDIO_VOICE_LINE: true });
  assert.deepEqual(ls.pickFlags('x'), ls.pickFlags(null));
});

test('整條管道：權杖、金鑰交給 keystore、stdin 關掉就結束', { skip: !DIR && '沒設 IAMDIRECTOR_LOCAL_SERVER_DIR' }, async () => {
  const up = await fakeUpstream();
  const data = fs.mkdtempSync(path.join(os.tmpdir(), 'ls-'));
  const ks = memKeystore();
  let exited = false;
  const srv = ls.start({
    spawn, keystore: ks, dataDir: data,
    runtime: ls.resolveRuntime({ isPackaged: false, env: { IAMDIRECTOR_LOCAL_SERVER_DIR: DIR }, platform: process.platform }),
    gatewayBase: 'http://127.0.0.1:' + up.address().port + '/v2',
    onExit: () => { exited = true; },
  });
  try {
    const port = await srv.ready;
    const base = 'http://127.0.0.1:' + port;
    assert.equal((await fetch(base + '/api/payer')).status, 401, '沒權杖要擋');
    const h = { [ls.TOKEN_HEADER]: srv.token, 'Content-Type': 'application/json' };
    const r = await fetch(base + '/api/payer/key', { method: 'POST', headers: h, body: JSON.stringify({ capability: 'video', key: GOOD }) });
    const d = await r.json();
    assert.equal(r.status, 200);
    assert.equal(d.persisted, true);
    assert.equal(ks.box.saved, GOOD, '驗證過的金鑰交給 keystore');
    assert.ok(!JSON.stringify(d).includes(GOOD), '回應只有末四碼');
    const bad = fs.mkdtempSync(path.join(os.tmpdir(), 'oh-'));
    fs.writeFileSync(path.join(bad, 'libopenh264.so.8'), 'not cisco');
    assert.equal(await srv.setOpenH264(bad), false, '雜湊不對不收');
    assert.equal(await srv.setOpenH264(null), true);
    const del = await fetch(base + '/api/payer/key/delete', { method: 'POST', headers: h, body: '{}' });
    assert.equal(del.status, 200);
    assert.equal(ks.box.cleared, 1);
    for (const f of fs.readdirSync(data, { recursive: true })) {
      const p = path.join(data, f);
      if (fs.statSync(p).isFile()) assert.ok(!fs.readFileSync(p).includes(GOOD), f);
    }
  } finally {
    srv.stop();
    await new Promise((ok) => { const t = setInterval(() => { if (exited) { clearInterval(t); ok(); } }, 50); });
    up.close();
  }
});

test('子程序一起來就結束：寫 stdin 的 EPIPE 不准變成未接住的錯誤', async () => {
  const { spawn: realSpawn } = require('node:child_process');
  let uncaught = null;
  const onErr = (e) => { uncaught = e; };
  process.on('uncaughtException', onErr);
  let order = [];
  const ks = { load: () => { order.push('load'); return null; }, save: () => ({}), clear: () => {} };
  const srv = ls.start({
    spawn: (...a) => { order.push('spawn'); return realSpawn(process.execPath, ['-e', 'process.exit(0)'], a[2]); },
    keystore: ks, dataDir: os.tmpdir(), runtime: { python: process.execPath, server: '-e' },
    onExit: () => {},
  });
  await srv.ready.catch(() => {});
  srv.stop();
  await new Promise((ok) => setTimeout(ok, 300));
  process.off('uncaughtException', onErr);
  assert.equal(uncaught, null, String(uncaught));
  assert.deepEqual(order.slice(0, 2), ['load', 'spawn'], '先讀金鑰再起子程序');
});
