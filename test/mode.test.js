'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { decide } = require('../src/mode');

test('沒選過、沒登入過：本機模式（不用註冊就能用）', () => {
  assert.equal(decide({}), 'local');
});
test('0.1.x 已登入的人升上來：維持雲端，不被丟進空的本機模式', () => {
  assert.equal(decide({ hasCloudSession: true }), 'cloud');
});
test('使用者選過就照他選的；亂值不算', () => {
  assert.equal(decide({ saved: 'local', hasCloudSession: true }), 'local');
  assert.equal(decide({ saved: 'cloud' }), 'cloud');
  assert.equal(decide({ saved: 'evil' }), 'local');
});
test('開發者指定 IAMDIRECTOR_URL：雲端', () => {
  assert.equal(decide({ envUrl: 'http://127.0.0.1:7802' }), 'cloud');
});
