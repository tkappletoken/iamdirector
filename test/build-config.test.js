'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const mac = pkg.build.mac;
const WF = path.join(root, '.github', 'workflows', 'release.yml');
const wf = fs.readFileSync(WF, 'utf8');
const REL = {};
// Split a workflow into its top-level jobs: { name: text }
function jobs(src) {
  const body = src.slice(src.indexOf('\njobs:\n') + 7);
  const out = {};
  for (const m of body.split(/\n(?=  [A-Za-z0-9_-]+:\n)/)) {
    const k = m.match(/^\s*([A-Za-z0-9_-]+):/);
    if (k) out[k[1]] = m;
  }
  return out;
}

test('mac：hardened runtime、兩份 entitlements 都存在、有 zip（自動更新要用）', () => {
  assert.equal(mac.hardenedRuntime, true);
  for (const k of ['entitlements', 'entitlementsInherit']) assert.ok(fs.existsSync(path.join(root, mac[k])), mac[k]);
  assert.ok(mac.target.some((t) => t.target === 'zip'));
  assert.ok(!('identity' in mac), 'identity 不寫死：有憑證時由 CSC_LINK 決定，沒有時 dist-mac.mjs 給 "-"');
});

test('entitlements 不開會削弱 hardened runtime 的權限', () => {
  for (const k of ['entitlements', 'entitlementsInherit']) {
    const x = (fs.readFileSync(path.join(root, mac[k]), 'utf8').match(/<key>[^<]*<\/key>/g) || []).join('\n');
    for (const bad of ['disable-library-validation', 'allow-dyld-environment-variables', 'get-task-allow']) {
      assert.ok(!x.includes(bad), `${mac[k]} 開了 ${bad}`);
    }
  }
});

test('dmg 外殼不簽', () => assert.equal(pkg.build.dmg.sign, false));

test('dist:mac 走 dist-mac.mjs（沒憑證時關掉鑰匙圈自動尋找）', () => {
  assert.match(pkg.scripts['dist:mac'], /dist-mac\.mjs/);
  const s = fs.readFileSync(path.join(root, 'scripts', 'dist-mac.mjs'), 'utf8');
  assert.match(s, /CSC_IDENTITY_AUTO_DISCOVERY = 'false'/);
});

test('workflow：只引用 Secrets 名稱、不含任何值；正式版強制公證；三項驗證都在', REL, () => {
  for (const k of ['CSC_LINK', 'CSC_KEY_PASSWORD', 'APPLE_API_KEY', 'APPLE_API_KEY_ID', 'APPLE_API_ISSUER']) {
    assert.ok(wf.includes(`secrets.${k}`), k);
  }
  assert.ok(!/BEGIN [A-Z ]*PRIVATE KEY-----\n[A-Za-z0-9+/]/.test(wf));
  assert.ok(!/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/.test(wf), 'Issuer ID 不寫死');
  assert.match(wf, /REQUIRE_NOTARIZE: '1'/);
  assert.match(fs.readFileSync(path.join(root, 'scripts', 'dist-mac.mjs'), 'utf8'), /'--publish', 'never'/);
  const v = fs.readFileSync(path.join(root, 'scripts', 'verify-mac.sh'), 'utf8');
  for (const c of ['codesign --verify --deep --strict', 'spctl -a -vv', 'stapler validate', 'flags=.*runtime']) assert.ok(v.includes(c), c);
});

test('workflow 安全：只有 tag 與手動觸發、預設唯讀、Secrets 只在宣告 production 環境的簽章那一步', REL, () => {
  const on = wf.slice(wf.indexOf('\non:'), wf.indexOf('\npermissions:'));
  assert.match(on, /tags:\s*\n\s*- 'desktop-v\*'/);
  assert.match(on, /workflow_dispatch:/);
  assert.ok(!/^\s+(pull_request|pull_request_target|workflow_run|issue_comment|repository_dispatch|schedule):/m.test(on), '只准 tag 與手動觸發');
  assert.ok(!/^\s+branches:/m.test(on), 'push 只准 tag');
  assert.match(wf, /^permissions:\n  contents: read$/m);
  assert.ok(!/run:[^\n]*\$\{\{\s*inputs\./.test(wf), 'inputs 不准直接插進 run');
  assert.match(wf, /\^desktop-v\[0-9\]\+/);
  assert.match(wf, /refs\/tags\/\*/, '手動觸發也要在 tag 上');
  const J = jobs(wf);
  for (const [name, text] of Object.entries(J)) {
    const env = /^    environment: production$/m.test(text);
    assert.equal(env, name === 'mac', `只有 mac job 宣告 environment: production（${name}）`);
    assert.equal(/^      contents: write$/m.test(text), name === 'publish', `只有 publish job 有 contents: write（${name}）`);
  }
  const steps = wf.split(/\n      - /).filter((x) => x.includes('secrets.'));
  assert.equal(steps.length, 1, 'Secrets 只准出現在「打包、簽章、公證」一步');
  assert.match(steps[0], /^name: 打包、簽章、公證/);
  assert.ok(!/RELEASES_TOKEN/.test(wf), '同一個 repo 發版，用 GITHUB_TOKEN');
});

test('發佈：不覆蓋已發佈的版本、三平台全成功才發、先 draft 全部上傳核對才公開、latest*.yml 一起發', REL, () => {
  const pub = jobs(wf).publish;
  assert.match(pub, /GH_TOKEN: \$\{\{ github\.token \}\}/);
  assert.ok(wf.indexOf('不能已經有這個版本') < wf.indexOf('npm ci'), '打包前先確認沒有這個版本');
  assert.match(pub, /gh release view "\$\{TAG\}"[^\n]*\n\s*echo "::error::[^\n]*不覆蓋"; exit 1/);
  assert.ok(!/--clobber/.test(wf), '上傳不准覆蓋既有檔案');
  const c = pub.indexOf('--draft '), u = pub.indexOf('gh release upload'), e = pub.indexOf('--draft=false');
  assert.ok(c > 0 && c < u && u < e, '順序要是：建 draft → 上傳 → 核對 → 公開');
  assert.match(pub, /--verify-tag/);
  assert.match(pub, /--latest/);
  assert.match(pub, /latest\*\.yml/);
  assert.ok(pub.indexOf('release-manifest.mjs') > 0 && pub.indexOf('release-manifest.mjs') < pub.indexOf('gh release create'));
  assert.match(pub, /needs: \[precheck, mac, linux, windows\]/);
});

test('自動更新：發佈來源是公開的 iamdirector（原 iamdirector-releases）（只認正式 release），設定裡沒有 token', () => {
  assert.deepEqual(pkg.build.publish, [{ provider: 'github', owner: 'tkappletoken', repo: 'iamdirector', releaseType: 'release' }]);
  for (const pub of pkg.build.publish) assert.ok(!Object.keys(pub).some((k) => /token/i.test(k)), 'publish 設定不能帶 token（會被打進 app-update.yml）');
});

test('測試版（prerelease）由 tag 訊息的「內部測試用，請勿下載」決定，不設 Latest，並讀回 /releases/latest 驗證', REL, () => {
  const pc = jobs(wf).precheck;
  assert.match(pc, /annotated tag/);
  assert.match(pc, /grep -q '內部測試用，請勿下載' notes\.md && pre=true/);
  assert.match(pc, /勾了 prerelease，但 tag 訊息沒有寫/);
  assert.ok(!/PRERELEASE:.*(ref_name|TAG|contains|startsWith)/.test(wf), 'prerelease 不能從 tag 名稱推出來');
  assert.match(wf, /PRERELEASE: \$\{\{ needs\.precheck\.outputs\.prerelease \}\}/);
  assert.match(wf, /--prerelease --latest=false/);
  assert.match(wf, /releases\/latest/);
});

test('CI 打包一律 --publish never（上傳只由 release.yml 的發佈 job 做）', REL, () => {
  const bc = fs.readFileSync(path.join(root, '.github', 'workflows', 'build-check.yml'), 'utf8');
  const dm = fs.readFileSync(path.join(root, 'scripts', 'dist-mac.mjs'), 'utf8');
  for (const [name, s] of [['release.yml', wf], ['build-check.yml', bc]]) {
    const calls = s.match(/npx electron-builder[^\n]*/g) || [];
    assert.ok(calls.length > 0, name);
    for (const c of calls) assert.match(c, /--publish never/, `${name}: ${c}`);
  }
  assert.match(dm, /'--publish', 'never'/);
});

test('mac：electronLanguages 只留 zh_TW、zh_CN、en（en 是英文系統的退路）', () => {
  assert.deepEqual(mac.electronLanguages, ['zh_TW', 'zh_CN', 'en']);
});

test('build-check.yml（分支上的打包檢查）不准碰任何 Secrets、不准發佈', () => {
  const bc = fs.readFileSync(path.join(root, '.github', 'workflows', 'build-check.yml'), 'utf8');
  assert.ok(!bc.includes('secrets.'), '打包檢查不讀 Secrets');
  assert.ok(!/gh release|--publish always|--publish onTag/.test(bc), '打包檢查不發佈');
  assert.ok(!/^\s+(tags|pull_request_target|workflow_dispatch):/m.test(bc));
});

test('Windows 上傳不帶 __uninstaller.exe（不然 release-manifest 會數到 4 個 exe 而擋下發佈）', REL, () => {
  assert.match(wf, /!dist\/\*__uninstaller\*/);
});
