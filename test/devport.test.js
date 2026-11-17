'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const d = require('../src/devport');

function fakeCommandLine(initial = {}) {
  const sw = new Map(Object.entries(initial));
  return {
    sw,
    hasSwitch: (k) => sw.has(k),
    removeSwitch: (k) => { sw.delete(k); },
    appendSwitch: (k, v = '') => { sw.set(k, v); },
  };
}
const quiet = { warn() {} };
const ENVS = [{}, { IAMDIRECTOR_DEV_PORT: '9229' }, { IAMDIRECTOR_DEV_PORT: '1' }, { IAMDIRECTOR_DEV_PORT: 'abc' }];
const ARGVS = [{}, { 'remote-debugging-port': '9229' }, { 'remote-debugging-pipe': '' },
  { 'remote-debugging-port': '9229', 'remote-debugging-address': '0.0.0.0' }];

test('打包版：不管環境變數或命令列參數是什麼，都不開', () => {
  for (const isPackaged of [true, undefined, 'false', 0]) {
    for (const env of ENVS) {
      assert.equal(d.decide({ isPackaged, env }).open, false, JSON.stringify({ isPackaged, env }));
      for (const argv of ARGVS) {
        const cl = fakeCommandLine(argv);
        const r = d.apply({ isPackaged, env, commandLine: cl, log: quiet });
        assert.equal(r.open, false);
        for (const s of d.SWITCHES) assert.ok(!cl.sw.has(s), `留下了 ${s}：${JSON.stringify({ isPackaged, env, argv })}`);
        assert.equal(!!r.refused, Object.keys(argv).length > 0, '命令列帶了除錯參數要回報 refused，讓 main.js 結束程式');
      }
    }
  }
});

test('開發模式但沒設 IAMDIRECTOR_DEV_PORT：不開，命令列塞的參數也拿掉', () => {
  for (const env of [{}, { IAMDIRECTOR_DEV_PORT: '' }, { OTHER: '9229' }]) {
    assert.equal(d.decide({ isPackaged: false, env }).open, false);
    for (const argv of ARGVS) {
      const cl = fakeCommandLine(argv);
      const r = d.apply({ isPackaged: false, env, commandLine: cl, log: quiet });
      assert.equal(r.open, false);
      assert.ok(!r.refused);
      for (const s of d.SWITCHES) assert.ok(!cl.sw.has(s), `留下了 ${s}`);
    }
  }
});

test('兩個條件都成立才開，而且綁 127.0.0.1（命令列塞 0.0.0.0 也蓋掉）', () => {
  const logs = [];
  const cl = fakeCommandLine({ 'remote-debugging-address': '0.0.0.0', 'remote-allow-origins': '*' });
  const r = d.apply({ isPackaged: false, env: { IAMDIRECTOR_DEV_PORT: '9229' }, commandLine: cl,
    log: { warn: (m) => logs.push(m) } });
  assert.deepEqual({ open: r.open, host: r.host, port: r.port }, { open: true, host: '127.0.0.1', port: 9229 });
  assert.equal(cl.sw.get('remote-debugging-address'), '127.0.0.1');
  assert.equal(cl.sw.get('remote-debugging-port'), '9229');
  assert.ok(!cl.sw.has('remote-allow-origins'), '不准讓網頁 origin 連 CDP');
  assert.deepEqual(logs, ['⚠ 開發除錯埠已開啟 127.0.0.1:9229（打包版不會有）']);
});

test('埠號不合法就在啟動時炸，不默默換一個', () => {
  for (const v of ['abc', '80', '0', '70000', '-1', '9e3']) {
    assert.throws(() => d.decide({ isPackaged: false, env: { IAMDIRECTOR_DEV_PORT: v } }), v);
  }
});

test('不是打包版就一律用獨立 userData（不管有沒有開除錯埠）；打包版不改', () => {
  assert.equal(d.devUserDataSuffix({ isPackaged: false }), '-dev');
  for (const isPackaged of [true, undefined, 'false', 0]) assert.equal(d.devUserDataSuffix({ isPackaged }), null, String(isPackaged));
  const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'main.js'), 'utf8');
  const a = src.indexOf("app.setPath('userData'");
  assert.ok(a > 0 && a < src.indexOf('requestSingleInstanceLock'), 'setPath 要在 single-instance lock 之前');
  assert.match(src, /const udSuffix = devport\.devUserDataSuffix\(\{ isPackaged: app\.isPackaged \}\);\s*if \(udSuffix\) app\.setPath/,
    'main.js 不能把 userData 隔離綁在 dbg.open 之類的條件上');
});

test('main.js 在 requestSingleInstanceLock 之前套用 devport，refused 時 app.exit', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'main.js'), 'utf8');
  const a = src.indexOf('devport.apply(');
  assert.ok(a > 0 && a < src.indexOf('requestSingleInstanceLock'), '要在最前面套用');
  assert.match(src, /isPackaged: app\.isPackaged/);
  assert.match(src, /if \(dbg\.refused\)[\s\S]{0,200}app\.exit\(1\)/);
  assert.ok(!/remote-debugging/.test(src), 'main.js 不准自己碰 remote-debugging 參數，只能經過 devport.js');
});
