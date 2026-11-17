'use strict';

const fs = require('node:fs');
const path = require('node:path');

const MARK = '<!--params-->';

function safeJson(obj) {
  return JSON.stringify(obj).replace(/[<>&\u2028\u2029]/g, (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));
}

function dataUrl(html, params) {
  if (!html.includes(MARK)) throw new Error('local page missing params marker');
  const block = `<script type="application/json" id="params">${safeJson(params || {})}</script>`;
  const out = html.replace(MARK, () => block);
  return 'data:text/html;charset=utf-8;base64,' + Buffer.from(out, 'utf8').toString('base64');
}

const cache = new Map();
function load(name, params) {
  if (!cache.has(name)) cache.set(name, fs.readFileSync(path.join(__dirname, name), 'utf8'));
  return dataUrl(cache.get(name), params);
}

module.exports = { MARK, safeJson, dataUrl, load };
