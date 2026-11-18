'use strict';

// Development-only switch: IAMDIRECTOR_UI=simple|full picks which UI the first page opens in.
// Packaged builds ignore it entirely, so released apps always open with the defaults.
const VALUES = { simple: '0', full: '1' };

function decide({ isPackaged, env }) {
  if (isPackaged !== false) return { advanced: null, reason: 'packaged' };
  const raw = env && env.IAMDIRECTOR_UI;
  if (raw === undefined || raw === '') return { advanced: null, reason: 'no-env' };
  const v = VALUES[String(raw).trim().toLowerCase()];
  if (v === undefined) return { advanced: null, reason: 'invalid', raw: String(raw) };
  return { advanced: v, reason: 'dev' };
}

function withUi(url, opts) {
  const d = decide(opts);
  if (d.advanced === null) return url;
  try {
    const u = new URL(url);
    if (!/^https?:$/.test(u.protocol)) return url;
    u.searchParams.set('advanced', d.advanced);
    return u.toString();
  } catch (_) { return url; }
}

module.exports = { decide, withUi, VALUES };
