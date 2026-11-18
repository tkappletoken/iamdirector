'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const d = require('../src/devui');

const URLS = ['http://127.0.0.1:51234/', 'http://127.0.0.1:51234/w/abc?x=1#k', 'https://iamdirector.app/'];
const ENVS = [{ IAMDIRECTOR_UI: 'full' }, { IAMDIRECTOR_UI: 'simple' }, { IAMDIRECTOR_UI: 'FULL' }, { IAMDIRECTOR_UI: 'x' }, {}];

test('打包版：就算設了 IAMDIRECTOR_UI，網址也原樣不動、不帶 advanced', () => {
  for (const isPackaged of [true, undefined, 'false', 0]) {
    for (const env of ENVS) {
      for (const url of URLS) {
        assert.equal(d.withUi(url, { isPackaged, env }), url, JSON.stringify({ isPackaged, env, url }));
        assert.ok(!/advanced=/.test(d.withUi(url, { isPackaged, env })));
      }
      assert.equal(d.decide({ isPackaged, env }).advanced, null);
    }
  }
});

test('開發模式：full 帶 advanced=1，simple 帶 advanced=0，原本的路徑與參數保留', () => {
  const full = new URL(d.withUi(URLS[1], { isPackaged: false, env: { IAMDIRECTOR_UI: 'full' } }));
  assert.equal(full.searchParams.get('advanced'), '1');
  assert.equal(full.searchParams.get('x'), '1');
  assert.equal(full.pathname, '/w/abc');
  assert.equal(full.hash, '#k');
  const simple = new URL(d.withUi(URLS[0], { isPackaged: false, env: { IAMDIRECTOR_UI: ' Simple ' } }));
  assert.equal(simple.searchParams.get('advanced'), '0');
});

test('開發模式但沒設或設錯：網址不動', () => {
  for (const env of [{}, { IAMDIRECTOR_UI: '' }, { IAMDIRECTOR_UI: 'advanced' }, { OTHER: 'full' }]) {
    for (const url of URLS) assert.equal(d.withUi(url, { isPackaged: false, env }), url);
  }
  assert.equal(d.decide({ isPackaged: false, env: { IAMDIRECTOR_UI: 'advanced' } }).reason, 'invalid');
  assert.equal(d.withUi('data:text/html,hi', { isPackaged: false, env: { IAMDIRECTOR_UI: 'full' } }), 'data:text/html,hi');
});

test('main.js 第一次載入的網址經過 devui.withUi，而且傳的是 app.isPackaged', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'main.js'), 'utf8');
  assert.match(src, /win\.loadURL\(devui\.withUi\(first, \{ isPackaged: app\.isPackaged, env: process\.env \}\)\)/);
  assert.ok(!/IAMDIRECTOR_UI/.test(src.replace(/console\.warn\([^\n]*\)/g, '')), 'main.js 不要自己讀 IAMDIRECTOR_UI，一律經 devui');
});
