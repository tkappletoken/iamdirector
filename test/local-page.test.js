'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const lp = require('../src/local-page');

const decode = (u) => Buffer.from(u.replace(/^data:text\/html;charset=utf-8;base64,/, ''), 'base64').toString('utf8');

test('dataUrl：參數放進 JSON 區塊，</script> 關不掉它', () => {
  const u = lp.dataUrl('<p>x</p><!--params--><script>1</script>', { u: 'https://iamdirector.app/w/1', d: '</script><script>alert(1)</script>' });
  assert.match(u, /^data:text\/html;charset=utf-8;base64,/);
  const html = decode(u);
  const m = /<script type="application\/json" id="params">(.*?)<\/script>/.exec(html);
  assert.ok(m);
  assert.deepEqual(JSON.parse(m[1]), { u: 'https://iamdirector.app/w/1', d: '</script><script>alert(1)</script>' });
  assert.equal(html.split('</script>').length - 1, 2, '只有 JSON 區塊和頁面程式各自的結尾');
  assert.ok(!html.includes('<!--params-->'));
});

test('dataUrl：值裡的 $& 之類不會被當成取代樣式', () => {
  const html = decode(lp.dataUrl('<!--params-->', { d: "$& $' $`" }));
  const m = /id="params">(.*?)<\/script>/.exec(html);
  assert.equal(JSON.parse(m[1]).d, "$& $' $`");
});

test('沒有記號就報錯（避免參數默默沒放進去）', () => {
  assert.throws(() => lp.dataUrl('<p>no marker</p>', {}));
});

for (const name of ['offline.html', 'login-wait.html']) {
  test(`${name}：有參數記號、CSP 的 sha256 跟頁面程式一致、不讀 location.search`, () => {
    const html = fs.readFileSync(path.join(__dirname, '..', 'src', name), 'utf8');
    assert.ok(html.includes(lp.MARK));
    const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
    assert.equal(scripts.length, 1);
    const want = crypto.createHash('sha256').update(scripts[0]).digest('base64');
    assert.ok(html.includes(`script-src 'sha256-${want}'`), 'CSP hash 過期了：改了頁面程式要重算');
    assert.ok(!scripts[0].includes('location.search'));
    const url = lp.load(name, { u: 'https://iamdirector.app/' });
    assert.ok(decode(url).includes('id="params"'));
  });
}
