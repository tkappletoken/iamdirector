'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const dir = path.join(__dirname, '..', 'local-server');

function pyFiles(d) {
  return fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(d, e.name);
    return e.isDirectory() ? pyFiles(p) : e.name.endsWith('.py') ? [p] : [];
  });
}

test('every template slot the local server replaces is present in local-server/ui2.html', () => {
  const page = fs.readFileSync(path.join(dir, 'ui2.html'), 'utf8');
  const slots = new Set();
  for (const f of pyFiles(dir)) {
    for (const m of fs.readFileSync(f, 'utf8').matchAll(/["'](<!--\s*[A-Z][A-Z0-9-]*\s*-->)["']/g)) slots.add(m[1]);
  }
  assert.ok(slots.size > 0, 'no slots found in local-server/*.py (the scan itself is broken)');
  for (const s of slots) assert.ok(page.includes(s), `local-server/ui2.html is missing ${s}`);
});
