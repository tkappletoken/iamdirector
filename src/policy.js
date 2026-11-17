'use strict';

const PROD_URL = 'https://iamdirector.app';

const APP_ORIGINS = [
  'https://iamdirector.app',
  'https://www.iamdirector.app',
  'https://studio.appletoken.app',
];

const OAUTH_HOSTS = [
  'accounts.google.com',
  'accounts.youtube.com',
  'github.com',
  'access.line.me',
];

function startUrl(env) {
  const raw = (env && env.IAMDIRECTOR_URL) || PROD_URL;
  const u = new URL(raw);
  if (u.protocol !== 'https:' && !isLoopback(u)) {
    throw new Error('IAMDIRECTOR_URL 只接受 https，或本機 http://127.0.0.1 / localhost：' + raw);
  }
  return u.toString();
}

function isLoopback(u) {
  return u.protocol === 'http:' && (u.hostname === '127.0.0.1' || u.hostname === 'localhost');
}

function parse(url) {
  try { return new URL(url); } catch (_) { return null; }
}

let LOCAL_ONLY = false;
function setLocalOnly(v) { LOCAL_ONLY = !!v; }

function appOrigins(start) {
  if (LOCAL_ONLY) { const s = parse(start); return s ? [s.origin] : []; }
  const list = APP_ORIGINS.slice();
  const s = parse(start);
  if (s && !list.includes(s.origin)) list.push(s.origin);
  return list;
}

function isAppUrl(url, start) {
  const u = parse(url);
  return !!u && appOrigins(start).includes(u.origin);
}

function isAllowedNavigation(url, start) {
  const u = parse(url);
  if (!u) return false;
  if (isAppUrl(url, start)) return true;
  return !LOCAL_ONLY && u.protocol === 'https:' && OAUTH_HOSTS.includes(u.hostname);
}

const PROD_FAMILY = ['https://iamdirector.app', 'https://www.iamdirector.app'];
const NO_RESTORE_PATHS = ['/login', '/logout', '/reset', '/forgot', '/signup', '/register'];
const NO_RESTORE_PREFIXES = ['/auth/', '/sso/', '/api/', '/oauth/'];
const NO_RESTORE_PARAMS = ['token', 'code', 'state', 'ticket', 'key', 'password', 'session'];

function isRestorableUrl(url, start) {
  const u = parse(url);
  const s = parse(start);
  if (!u || !s || !isAppUrl(url, start)) return false;
  if (u.origin !== s.origin && !(PROD_FAMILY.includes(u.origin) && PROD_FAMILY.includes(s.origin))) return false;
  if (u.username || u.password) return false;
  const p = u.pathname.replace(/\/+$/, '').toLowerCase() || '/';
  if (NO_RESTORE_PATHS.includes(p)) return false;
  if (NO_RESTORE_PREFIXES.some((x) => (p + '/').startsWith(x))) return false;
  for (const k of u.searchParams.keys()) {
    if (NO_RESTORE_PARAMS.some((x) => k.toLowerCase().includes(x))) return false;
  }
  return true;
}

function isSafeExternal(url) {
  const u = parse(url);
  return !!u && ['https:', 'http:', 'mailto:'].includes(u.protocol);
}

function isDownloadUrl(url, start) {
  const u = parse(url);
  if (!u) return false;
  if (!LOCAL_ONLY && u.protocol === 'https:' && /^[a-z0-9.-]+\.s3[.-]([a-z0-9-]+\.)?amazonaws\.com$/.test(u.hostname)) return true;
  if (!isAppUrl(url, start)) return false;
  if (u.pathname === '/api/download') return true;
  if (u.pathname === '/api/export/file') return true;
  if (u.pathname === '/api/assets/content' && u.searchParams.get('download') === '1') return true;
  if (u.pathname.startsWith('/output/')) return true;
  return false;
}

function downloadFilename(suggested, url, mime) {
  let name = String(suggested || '').replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').trim();
  const u = parse(url);
  if (!name || name === 'download') {
    const id = u && u.searchParams.get('id');
    name = 'iamdirector-' + (id ? id.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 40) : Date.now());
  }
  if (!/\.[A-Za-z0-9]{2,5}$/.test(name)) {
    const ext = { 'video/mp4': '.mp4', 'image/png': '.png', 'image/jpeg': '.jpg', 'audio/mpeg': '.mp3',
      'application/x-subrip': '.srt', 'application/json': '.json' }[String(mime || '').split(';')[0]];
    if (ext) name += ext;
  }
  return name;
}

const QUIET_EXT = new Set(['.mp4', '.mov', '.webm', '.m4v', '.png', '.jpg', '.jpeg', '.webp', '.gif',
  '.mp3', '.wav', '.m4a', '.aac', '.srt', '.vtt', '.json']);
function isQuietDownload(filename) {
  const m = /\.[A-Za-z0-9]+$/.exec(String(filename || ''));
  return !!m && QUIET_EXT.has(m[0].toLowerCase());
}

const BASELINE_CSP = "object-src 'none'; base-uri 'self'; frame-ancestors 'none'";

module.exports = {
  PROD_URL, APP_ORIGINS, OAUTH_HOSTS, BASELINE_CSP,
  startUrl, setLocalOnly, isAppUrl, isAllowedNavigation, isRestorableUrl, isSafeExternal, isDownloadUrl, downloadFilename, isQuietDownload,
};
