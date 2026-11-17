'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const p = require('../src/policy');

const PROD = 'https://iamdirector.app/';
const DEV = 'http://127.0.0.1:7802/';

test('startUrl：預設正式站；只收 https 或本機 http', () => {
  assert.equal(p.startUrl({}), PROD);
  assert.equal(p.startUrl({ IAMDIRECTOR_URL: 'http://127.0.0.1:7802' }), DEV);
  assert.throws(() => p.startUrl({ IAMDIRECTOR_URL: 'http://evil.example' }));
  assert.throws(() => p.startUrl({ IAMDIRECTOR_URL: 'file:///etc/passwd' }));
  assert.throws(() => p.startUrl({ IAMDIRECTOR_URL: 'not a url' }));
});

test('導覽：工作台與 OAuth 網域放行', () => {
  for (const u of ['https://iamdirector.app/w/1', 'https://studio.appletoken.app/',
    'https://accounts.google.com/o/oauth2/v2/auth?x=1', 'https://github.com/login/oauth/authorize',
    'https://access.line.me/oauth2/v2.1/authorize']) {
    assert.ok(p.isAllowedNavigation(u, PROD), u);
  }
  assert.ok(p.isAllowedNavigation('http://127.0.0.1:7802/projects', DEV));
});

test('導覽：其他一律擋（含長得像的網域、http 版、別的 port）', () => {
  for (const u of ['https://iamdirector.app.evil.com/', 'https://evil.com/?https://iamdirector.app',
    'http://iamdirector.app/', 'http://accounts.google.com/', 'https://gist.github.com/',
    'https://checkout.stripe.com/pay', 'file:///etc/passwd', 'javascript:alert(1)',
    'https://www.google.com/', 'http://127.0.0.1:7802/']) {
    assert.equal(p.isAllowedNavigation(u, PROD), false, u);
  }
  assert.equal(p.isAllowedNavigation('http://127.0.0.1:9999/', DEV), false);
});

test('外部開啟只交 http(s)／mailto', () => {
  assert.ok(p.isSafeExternal('https://youtube.com/x'));
  assert.ok(p.isSafeExternal('mailto:a@b.c'));
  for (const u of ['file:///Applications/Calculator.app', 'javascript:1', 'smb://x/y', 'vscode://x', 'garbage']) {
    assert.equal(p.isSafeExternal(u), false, u);
  }
});

test('下載判斷：S3 預簽與同源下載端點', () => {
  assert.ok(p.isDownloadUrl('https://bkt.s3.ap-northeast-1.amazonaws.com/a.mp4?X-Amz-Signature=1', PROD));
  assert.ok(p.isDownloadUrl('https://bkt.s3.amazonaws.com/a.mp4', PROD));
  assert.ok(p.isDownloadUrl('https://iamdirector.app/api/download?id=abc', PROD));
  assert.ok(p.isDownloadUrl('https://iamdirector.app/api/assets/content?download=1&id=x', PROD));
  assert.equal(p.isDownloadUrl('https://iamdirector.app/api/assets/content?id=x', PROD), false);
  assert.equal(p.isDownloadUrl('https://evil.com/api/download?id=1', PROD), false);
  assert.equal(p.isDownloadUrl('https://s3.amazonaws.com.evil.com/a.mp4', PROD), false);
  assert.equal(p.isDownloadUrl('http://bkt.s3.amazonaws.com/a.mp4', PROD), false);
});

test('下載檔名：補上 id 與副檔名、清掉路徑字元', () => {
  assert.equal(p.downloadFilename('download', 'https://iamdirector.app/api/download?id=job_1', 'video/mp4'), 'iamdirector-job_1.mp4');
  assert.equal(p.downloadFilename('成片.mp4', 'https://x/', 'video/mp4'), '成片.mp4');
  assert.equal(p.downloadFilename('../../etc/x', 'https://x/', ''), '.._.._etc_x');
});

test('不問就存只限媒體檔；可執行檔、壓縮檔、沒副檔名的都要跳視窗', () => {
  for (const n of ['成片.mp4', 'a.PNG', 'sub.srt', 'x.mp3']) assert.ok(p.isQuietDownload(n), n);
  for (const n of ['x.app', 'x.dmg', 'x.pkg', 'x.command', 'x.exe', 'x.zip', 'x.sh', 'noext', 'x.mp4.app', '']) {
    assert.equal(p.isQuietDownload(n), false, n);
  }
});

test('重開網址：站內一般頁面記得住（含 www 與 apex 互通、本機開發同源）', () => {
  for (const u of ['https://iamdirector.app/', 'https://iamdirector.app/w/123?tab=story#shot-4',
    'https://www.iamdirector.app/projects', 'https://iamdirector.app/authors']) {
    assert.ok(p.isRestorableUrl(u, PROD), u);
  }
  assert.ok(p.isRestorableUrl('http://127.0.0.1:7802/w/1', DEV));
});

test('重開網址：別的網域、登入／OAuth 中途、API、帶一次性憑證的一律退回首頁', () => {
  for (const u of [
    'https://evil.example/w/1', 'https://iamdirector.app.evil.example/', 'http://iamdirector.app/w/1',
    'https://accounts.google.com/o/oauth2/auth', 'https://github.com/login/oauth/authorize',
    'https://studio.appletoken.app/w/1',
    'http://127.0.0.1:7802/w/1',
    'https://iamdirector.app/login', 'https://iamdirector.app/login?mode=register', 'https://iamdirector.app/Login/',
    'https://iamdirector.app/reset?t=abc', 'https://iamdirector.app/logout',
    'https://iamdirector.app/auth/google', 'https://iamdirector.app/auth/github/callback?code=x&state=y',
    'https://iamdirector.app/api/download?id=1', 'https://iamdirector.app/w/1?token=abc',
    'https://iamdirector.app/w/1?reset_token=abc', 'https://user:pw@iamdirector.app/w/1',
    'file:///etc/passwd', 'javascript:alert(1)', 'not a url', '',
  ]) {
    assert.equal(p.isRestorableUrl(u, PROD), false, u);
  }
  assert.equal(p.isRestorableUrl('https://iamdirector.app/w/1', DEV), false, '本機開發時不跳回正式站');
});

test('本機模式：只有本機伺服器自己算 app；正式站、OAuth、S3 都不算', () => {
  const LOCAL = 'http://127.0.0.1:53123/';
  p.setLocalOnly(true);
  try {
    assert.ok(p.isAppUrl('http://127.0.0.1:53123/w/1', LOCAL));
    for (const u of ['https://iamdirector.app/', 'https://www.iamdirector.app/x', 'http://127.0.0.1:53124/']) {
      assert.ok(!p.isAppUrl(u, LOCAL), u);
      assert.ok(!p.isAllowedNavigation(u, LOCAL), u);
    }
    assert.ok(!p.isAllowedNavigation('https://accounts.google.com/o/oauth2/v2/auth', LOCAL));
    assert.ok(!p.isDownloadUrl('https://bucket.s3.amazonaws.com/x.mp4', LOCAL));
    assert.ok(p.isDownloadUrl('http://127.0.0.1:53123/api/download?id=job_1', LOCAL));
    assert.ok(p.isDownloadUrl('http://127.0.0.1:53123/api/export/file?id=exp_abcdefgh&kind=mp4', LOCAL), '本機匯出的成品要走下載，不能丟給系統瀏覽器（沒權杖會 401）');
  } finally {
    p.setLocalOnly(false);
  }
  assert.ok(p.isAppUrl('https://iamdirector.app/', PROD), '關掉之後恢復雲端的規則');
});
