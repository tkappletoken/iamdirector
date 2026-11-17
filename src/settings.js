'use strict';
const fs = require('node:fs');
const path = require('node:path');

let file = null;
let data = {};

function init(dir) {
  file = path.join(dir, 'settings.json');
  try { data = JSON.parse(fs.readFileSync(file, 'utf8')) || {}; } catch (_) { data = {}; }
}

function get() { return data; }

function set(patch) {
  data = { ...data, ...patch };
  if (!file) return;
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file + '.tmp', JSON.stringify(data, null, 2), { mode: 0o600 });
    fs.renameSync(file + '.tmp', file);
  } catch (_) { }
}

module.exports = { init, get, set };
