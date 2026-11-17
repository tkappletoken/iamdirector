'use strict';

const crypto = require('node:crypto');

const PROTOCOL = 'iamdirector';
const PROVIDERS = ['google', 'github', 'line'];
const PENDING_TTL_MS = 5 * 60 * 1000;

const PROVIDER_HOSTS = {
  'accounts.google.com': 'google',
  'github.com': 'github',
  'access.line.me': 'line',
};

function parse(url) {
  try { return new URL(url); } catch (_) { return null; }
}

function b64url(buf) {
  return buf.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function createPkce(randomBytes = crypto.randomBytes) {
  const verifier = b64url(randomBytes(32));
  const challenge = b64url(crypto.createHash('sha256').update(verifier).digest());
  return { verifier, challenge };
}

function loginProvider(url, isAppUrl) {
  const u = parse(url);
  if (!u) return null;
  if (isAppUrl(url)) {
    const m = /^\/auth\/([a-z]+)\/?$/.exec(u.pathname);
    if (!m || !PROVIDERS.includes(m[1]) || u.searchParams.get('desktop') === '1') return null;
    return m[1];
  }
  if (u.protocol !== 'https:') return null;
  const p = PROVIDER_HOSTS[u.hostname];
  if (!p) return null;
  if (p === 'github' && !u.pathname.startsWith('/login')) return null;
  return p;
}

function externalStartUrl(start, provider, challenge, original) {
  if (!PROVIDERS.includes(provider)) throw new Error('unknown provider');
  const u = new URL('/auth/' + provider, start);
  u.searchParams.set('desktop', '1');
  u.searchParams.set('challenge', challenge);
  const o = parse(original);
  const next = o && o.searchParams.get('next');
  if (next && next.startsWith('/') && !next.startsWith('//')) u.searchParams.set('next', next);
  return u.toString();
}

function parseCallback(url) {
  const u = parse(url);
  if (!u || u.protocol !== PROTOCOL + ':') return null;
  if (u.hostname !== 'auth' || u.pathname !== '/callback' || u.username || u.password || u.port) return null;
  const code = u.searchParams.get('code');
  if (!code || !/^[A-Za-z0-9_-]{43}$/.test(code)) return null;
  return { code };
}

function findProtocolArg(argv) {
  return (argv || []).find((a) => typeof a === 'string' && a.toLowerCase().startsWith(PROTOCOL + '://')) || null;
}

function createPending(now = Date.now) {
  let cur = null;
  const used = new Set();
  return {
    begin(provider) {
      const { verifier, challenge } = createPkce();
      cur = { provider, verifier, at: now() };
      return { provider, challenge };
    },
    peek() {
      if (cur && now() - cur.at > PENDING_TTL_MS) cur = null;
      return cur ? { provider: cur.provider, verifier: cur.verifier } : null;
    },
    finish() { cur = null; },
    seen(code) {
      const h = crypto.createHash('sha256').update(code).digest('hex');
      if (used.has(h)) return true;
      used.add(h);
      if (used.size > 20) used.delete(used.values().next().value);
      return false;
    },
    cancel() { cur = null; },
    active() { return !!cur && now() - cur.at <= PENDING_TTL_MS; },
    provider() { return cur ? cur.provider : null; },
  };
}

module.exports = {
  PROTOCOL, PROVIDERS, PENDING_TTL_MS,
  createPkce, loginProvider, externalStartUrl, parseCallback, findProtocolArg, createPending,
};
