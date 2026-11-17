'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const x = require('../src/external-login');
const policy = require('../src/policy');

const PROD = 'https://iamdirector.app/';
const isApp = (u) => policy.isAppUrl(u, PROD);
const CODE = 'A'.repeat(21) + '_' + 'b'.repeat(20) + '-';

test('PKCE：verifier 43 字元 base64url、challenge 是它的 S256（無 padding）', () => {
  const { verifier, challenge } = x.createPkce();
  assert.match(verifier, /^[A-Za-z0-9_-]{43}$/);
  assert.match(challenge, /^[A-Za-z0-9_-]{43}$/);
  const want = crypto.createHash('sha256').update(verifier).digest('base64url');
  assert.equal(challenge, want);
  assert.notEqual(x.createPkce().verifier, verifier);
  const fixed = Buffer.from([116, 24, 223, 180, 151, 153, 224, 37, 79, 250, 96, 125, 216, 173, 187, 186,
    22, 212, 37, 77, 105, 214, 191, 240, 91, 88, 5, 88, 83, 132, 141, 121]);
  const v = x.createPkce(() => fixed);
  assert.equal(v.verifier, 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk');
  assert.equal(v.challenge, 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM');
});

test('攔截：工作台的 /auth/<provider> 與 provider 授權頁', () => {
  assert.equal(x.loginProvider('https://iamdirector.app/auth/google', isApp), 'google');
  assert.equal(x.loginProvider('https://iamdirector.app/auth/github?next=/w/1', isApp), 'github');
  assert.equal(x.loginProvider('https://www.iamdirector.app/auth/line', isApp), 'line');
  assert.equal(x.loginProvider('https://accounts.google.com/o/oauth2/v2/auth?client_id=1', isApp), 'google');
  assert.equal(x.loginProvider('https://github.com/login/oauth/authorize?x=1', isApp), 'github');
  assert.equal(x.loginProvider('https://access.line.me/oauth2/v2.1/authorize', isApp), 'line');
});

test('攔截：不該攔的不攔（callback、已帶 desktop=1、別的網域、別的 provider、一般 GitHub 頁）', () => {
  for (const u of [
    'https://iamdirector.app/auth/google/callback?code=1&state=2',
    'https://iamdirector.app/auth/google?desktop=1&challenge=abc',
    'https://iamdirector.app/auth/facebook',
    'https://iamdirector.app/auth/',
    'https://iamdirector.app/login',
    'https://evil.com/auth/google',
    'https://iamdirector.app.evil.com/auth/google',
    'http://accounts.google.com/o/oauth2/v2/auth',
    'https://github.com/tkappletoken',
    'https://gist.github.com/login',
    'not a url',
  ]) assert.equal(x.loginProvider(u, isApp), null, u);
});

test('交給瀏覽器的網址：desktop=1＋challenge，只轉站內 next', () => {
  const u = new URL(x.externalStartUrl(PROD, 'google', 'C'.repeat(43), 'https://iamdirector.app/auth/google?next=/w/9&evil=1'));
  assert.equal(u.origin + u.pathname, 'https://iamdirector.app/auth/google');
  assert.equal(u.searchParams.get('desktop'), '1');
  assert.equal(u.searchParams.get('challenge'), 'C'.repeat(43));
  assert.equal(u.searchParams.get('next'), '/w/9');
  assert.equal(u.searchParams.get('evil'), null);
  for (const n of ['//evil.com', 'https://evil.com/']) {
    const v = new URL(x.externalStartUrl(PROD, 'line', 'c', 'https://iamdirector.app/auth/line?next=' + encodeURIComponent(n)));
    assert.equal(v.searchParams.get('next'), null, n);
  }
  assert.throws(() => x.externalStartUrl(PROD, 'facebook', 'c'));
});

test('回呼：只收 iamdirector://auth/callback?code=<43 字元>', () => {
  assert.deepEqual(x.parseCallback('iamdirector://auth/callback?code=' + CODE), { code: CODE });
  for (const u of [
    'iamdirector://auth/callback',
    'iamdirector://auth/callback?code=short',
    'iamdirector://auth/callback?code=' + CODE + 'x',
    'iamdirector://auth/callback?code=' + CODE.slice(0, 42) + '%2F',
    'iamdirector://auth/other?code=' + CODE,
    'iamdirector://evil/callback?code=' + CODE,
    'iamdirector://user@auth/callback?code=' + CODE,
    'iamdirector://auth:99/callback?code=' + CODE,
    'https://auth/callback?code=' + CODE,
    'other://auth/callback?code=' + CODE,
    'garbage',
  ]) assert.equal(x.parseCallback(u), null, u);
});

test('argv 裡找協定網址（Windows／Linux second-instance）', () => {
  assert.equal(x.findProtocolArg(['/app/iamdirector', '--flag', 'iamdirector://auth/callback?code=1']),
    'iamdirector://auth/callback?code=1');
  assert.equal(x.findProtocolArg(['/app/iamdirector', 'https://x']), null);
  assert.equal(x.findProtocolArg(undefined), null);
});

test('verifier：換成功才丟、5 分鐘作廢、再開一次換掉舊的、取消就沒了', () => {
  let t = 1000;
  const p = x.createPending(() => t);
  const a = p.begin('google');
  assert.match(a.challenge, /^[A-Za-z0-9_-]{43}$/);
  const got = p.peek();
  assert.equal(got.provider, 'google');
  assert.equal(crypto.createHash('sha256').update(got.verifier).digest('base64url'), a.challenge);
  assert.deepEqual(p.peek(), got, '換之前（例如收到假 code 換失敗）verifier 還在');
  p.finish();
  assert.equal(p.peek(), null, '換成功後就沒了');

  p.begin('github');
  t += x.PENDING_TTL_MS + 1;
  assert.equal(p.active(), false);
  assert.equal(p.peek(), null, '過期');

  const first = p.begin('google');
  const second = p.begin('line');
  const v = p.peek();
  assert.equal(v.provider, 'line');
  assert.notEqual(crypto.createHash('sha256').update(v.verifier).digest('base64url'), first.challenge);
  assert.equal(crypto.createHash('sha256').update(v.verifier).digest('base64url'), second.challenge);

  p.begin('google');
  p.cancel();
  assert.equal(p.peek(), null, '取消');
});

test('重複的 code 只處理一次', () => {
  const p = x.createPending();
  assert.equal(p.seen(CODE), false);
  assert.equal(p.seen(CODE), true);
  assert.equal(p.seen(CODE.replace('A', 'Z')), false);
});

test('打包設定註冊 iamdirector 協定', () => {
  const pkg = require('../package.json');
  assert.ok(pkg.build.protocols.some((p) => p.schemes.includes(x.PROTOCOL)));
});
