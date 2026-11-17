'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { decide, moveNotice } = require('../src/mode');

test('打包版：不管以前選過什麼、有沒有登入過，一律本機模式', () => {
  for (const x of [{}, { saved: 'cloud' }, { hasCloudSession: true }, { envUrl: 'https://example.com' }]) {
    assert.equal(decide({ ...x, packaged: true }), 'local', JSON.stringify(x));
  }
});
test('開發版：IAMDIRECTOR_URL 是開發用的開關（雲端）；沒設就是本機', () => {
  assert.equal(decide({ envUrl: 'http://127.0.0.1:7802', packaged: false }), 'cloud');
  assert.equal(decide({ packaged: false }), 'local');
  assert.equal(decide({ saved: 'cloud', packaged: false }), 'local', '以前存的 cloud 不再決定模式');
});
test('升級說明：以前用雲端模式的人跳一次，看過就不再跳', () => {
  assert.equal(moveNotice({ saved: 'cloud' }), true);
  assert.equal(moveNotice({ hasCloudSession: true }), true, '0.1.x 沒選過、已登入：也是雲端模式的人');
  assert.equal(moveNotice({ saved: 'local', hasCloudSession: true }), false, '選過本機模式的人不用說明');
  assert.equal(moveNotice({}), false);
  assert.equal(moveNotice({ saved: 'cloud', noticed: true }), false, '只跳一次');
});
