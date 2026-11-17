'use strict';

const FIRST_CHECK_MS = 5 * 1000;
const CHECK_EVERY_MS = 30 * 60 * 1000;

function enabled({ isPackaged, platform, env }) {
  if (!isPackaged) return false;
  if (platform === 'linux') return !!(env && env.APPIMAGE);
  return platform === 'darwin' || platform === 'win32';
}

function parse(v) {
  const m = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/.exec(String(v || '').trim());
  return m ? { major: +m[1], minor: +m[2], patch: +m[3], pre: m[4] || '' } : null;
}

function classify(current, next) {
  const a = parse(current);
  const b = parse(next);
  if (!a || !b) return null;
  const cmp = (b.major - a.major) || (b.minor - a.minor) || (b.patch - a.patch);
  if (cmp < 0) return null;
  if (cmp === 0) {
    if (!(a.pre && !b.pre)) return null;
    return 'major';
  }
  if (b.pre) return 'major';
  return b.major === a.major && b.minor === a.minor ? 'patch' : 'major';
}

function allowPrerelease(settings) {
  return !!settings && settings.updatePrerelease === true;
}

function selfUpdateBlocked({ platform, exePath, inApplications }) {
  if (platform !== 'darwin') return null;
  if (String(exePath || '').includes('/AppTranslocation/')) return 'translocated';
  if (!inApplications) return 'not-in-applications';
  return null;
}

module.exports = { FIRST_CHECK_MS, CHECK_EVERY_MS, enabled, classify, parse, allowPrerelease, selfUpdateBlocked };
